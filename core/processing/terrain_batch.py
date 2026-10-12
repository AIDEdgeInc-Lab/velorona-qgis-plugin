"""Processing algorithm: terrain clearance for many Fixed Service links ("velorona:terrain_clearance_batch").

A thin adapter. The calculation, the per-row statuses and the CSV are core/batch.py, which runs every link through exactly the code a single selected link uses; this file
only reads features (reprojecting endpoints to EPSG:4326), reports progress, honours cancel, and writes the result table. It has NOT been run in a real QGIS in the change that
added it: tests/qgis_batch_e2e.py is the runtime test (needs QGIS 4; see tests/README.md). The enum names follow the QGIS 3.36+/4 scoped style used elsewhere in this plugin.
"""

from __future__ import annotations

from qgis.core import (
    NULL,
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsPointXY,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
)
from qgis.PyQt.QtCore import QVariant

from .. import batch as batchmod

INPUT, MAX_LINKS, FALLBACK_FREQUENCY, PAUSE, OUTPUT, CSV = "INPUT", "MAX_LINKS", "FALLBACK_FREQUENCY_GHZ", "PAUSE_SECONDS", "OUTPUT", "CSV"
WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")

_INT = {"batch_index", "source_fid", "elevation_samples"}
_BOOL = {"transient", "near_threshold"}
_DOUBLE = {"distance_km", "bearing_deg", "frequency_ghz", "site_a_height_m", "site_b_height_m", "first_fresnel_radius_m", "required_clearance_m", "available_clearance_m",
           "margin_m", "clearance_ratio", "percent_fresnel_clear", "critical_distance_from_a_km"}


def _qvariant(column: str):
    return QVariant.Int if column in _INT else QVariant.Bool if column in _BOOL else QVariant.Double if column in _DOUBLE else QVariant.String


def _py(value):
    """A QGIS NULL is not a Python None; the engine code treats both as absent."""
    return None if value is None or value == NULL else value


class TerrainClearanceBatch(QgsProcessingAlgorithm):
    def name(self):
        return "terrain_clearance_batch"

    def displayName(self):
        return "Terrain clearance for many Fixed Service links"

    def group(self):
        return "Velorona"

    def groupId(self):
        return "velorona"

    def createInstance(self):
        return TerrainClearanceBatch()

    def shortHelpString(self):
        return (
            "Runs Terrestrial Path Clearance for every link of a Fixed Service link layer (or only its selected features), one row per link.\n\n"
            "Each row is the same calculation as selecting that link and running Analyze: Terrestrial Path Clearance with the pre-filled values: the record's own highest published "
            "frequency (Observed) and the record's own antenna heights where it carries them (Observed), otherwise 30 m (Assumed).\n\n"
            "Status per link: CLEAR, WATCH, AT RISK, CRITICAL (terrain result; WATCH below a provisional 1.3 clearance ratio); NO DATA (a required input is missing or invalid, or "
            "elevation data could not be retrieved -- the reason is in the table; nothing is guessed); ERROR (unexpected failure for that link); NOT RUN (over the limit or cancelled). "
            "One link failing never stops the others.\n\n"
            "A record that publishes no usable frequency is NO DATA unless you enter a fallback frequency (then it is typed Assumed). Layers that are not Velorona Fixed Service layers "
            "carry no record frequency or heights: give a fallback frequency, or every link will be NO DATA.\n\n"
            "Limits: each link makes one elevation request (Open-Meteo, 90 m surface model that may include canopy and rooftops); the provider rate-limits, so a run is capped "
            "(default 100 links) and you can add a pause between links. Terrain only: no weather exposure in this algorithm. Not an outage prediction.\n\n"
            "Input geometry is read, never modified; endpoints are reprojected to EPSG:4326. The result layer keeps each link's geometry and adds the row's fields; the optional CSV carries "
            "the same rows with the product, library and convention header."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(INPUT, "Fixed Service links (line layer; only selected features if you choose so)",
                                                              [Qgis.ProcessingSourceType.VectorLine]))
        self.addParameter(QgsProcessingParameterNumber(MAX_LINKS, "Most links to analyse in one run", Qgis.ProcessingNumberParameterType.Integer,
                                                       defaultValue=batchmod.DEFAULT_MAX_LINKS, minValue=1, maxValue=batchmod.HARD_MAX_LINKS))
        self.addParameter(QgsProcessingParameterNumber(FALLBACK_FREQUENCY, "Fallback frequency (GHz) for records that publish none (typed Assumed; leave empty for NO DATA)",
                                                       Qgis.ProcessingNumberParameterType.Double, optional=True, minValue=0.1, maxValue=100.0))
        self.addParameter(QgsProcessingParameterNumber(PAUSE, "Pause between links (seconds), to stay under the elevation provider's rate limit",
                                                       Qgis.ProcessingNumberParameterType.Double, defaultValue=0.0, minValue=0.0, maxValue=30.0))
        self.addParameter(QgsProcessingParameterFeatureSink(OUTPUT, "Terrain clearance (batch)", Qgis.ProcessingSourceType.VectorLine))
        self.addParameter(QgsProcessingParameterFileDestination(CSV, "CSV export (optional)", "CSV files (*.csv)", optional=True, createByDefault=False))

    def checkParameterValues(self, parameters, context):
        source = self.parameterAsSource(parameters, INPUT, context)
        if source is None:
            return False, "Choose a link layer."
        limit = self.parameterAsInt(parameters, MAX_LINKS, context)
        count = source.featureCount()
        if count > limit:
            return False, (f"The input has {count} links, over the limit of {limit} for one run. Select fewer links, or raise the limit (at most {batchmod.HARD_MAX_LINKS}); "
                           "each link makes one elevation request and the provider rate-limits.")
        return True, ""

    def _links(self, source, context, feedback):
        transform = None
        if source.sourceCrs() != WGS84:
            transform = QgsCoordinateTransform(source.sourceCrs(), WGS84, context.transformContext())
        features, links = [], []
        for feature in source.getFeatures():
            if feedback.isCanceled():
                break
            attrs = {f.name(): _py(feature[f.name()]) for f in feature.fields()}
            a = b = None
            try:
                geom = feature.geometry()
                if geom is not None and not geom.isEmpty():
                    line = geom.asMultiPolyline()[0] if geom.isMultipart() else geom.asPolyline()
                    if len(line) >= 2:
                        pa, pb = QgsPointXY(line[0]), QgsPointXY(line[-1])
                        if transform is not None:
                            pa, pb = transform.transform(pa), transform.transform(pb)
                        a, b = (pa.y(), pa.x()), (pb.y(), pb.x())
            except Exception:   # an unreadable geometry is NO DATA for that link, with the reason, not a failed run
                a = b = None
            features.append(feature)
            links.append(batchmod.BatchLink(attrs=attrs, site_a=a, site_b=b, fid=feature.id()))
        return features, links

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, INPUT))
        max_links = self.parameterAsInt(parameters, MAX_LINKS, context)
        fallback = self.parameterAsDouble(parameters, FALLBACK_FREQUENCY, context) if parameters.get(FALLBACK_FREQUENCY) not in (None, "") else None
        pause = self.parameterAsDouble(parameters, PAUSE, context)

        features, links = self._links(source, context, feedback)
        feedback.pushInfo(f"{len(links)} link(s) read from the input.")
        if not links:
            feedback.pushInfo("Nothing to analyse: the input has no features (or only none are selected).")

        fields = QgsFields()
        for column in batchmod.COLUMNS:
            fields.append(QgsField(column, _qvariant(column)))
        sink, dest_id = self.parameterAsSink(parameters, OUTPUT, context, fields, source.wkbType(), source.sourceCrs())
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, OUTPUT))

        total = max(len(links), 1)

        def progress(done, _n, row):
            feedback.setProgress(100.0 * done / total)
            if row.status in (batchmod.NO_DATA, batchmod.STATUS_ERROR):
                feedback.pushInfo(f"{row.link_id}: {row.status} -- {row.reason}")

        result = batchmod.run_batch(links, fallback_frequency_ghz=fallback, max_links=max_links, progress=progress, is_canceled=feedback.isCanceled, pause_s=pause)

        for feature, row in zip(features, result.rows):
            out = QgsFeature(fields)
            out.setGeometry(feature.geometry())
            d = row.as_dict()
            out.setAttributes([d[c] for c in batchmod.COLUMNS])
            sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)

        counts = result.counts()
        feedback.pushInfo("Done: " + ", ".join(f"{s} {counts[s]}" for s in batchmod.ALL_STATUSES if counts[s]) + (" (cancelled)" if result.canceled else ""))

        outputs = {OUTPUT: dest_id}
        csv_path = self.parameterAsFileOutput(parameters, CSV, context) if parameters.get(CSV) not in (None, "") else None
        if csv_path:
            with open(csv_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(batchmod.batch_to_csv(result))
            outputs[CSV] = csv_path
            feedback.pushInfo(f"CSV written to {csv_path}")
        return outputs
