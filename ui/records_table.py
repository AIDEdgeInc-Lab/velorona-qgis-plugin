"""Velorona Records -- a curated table over the Velorona layers already in the
project, so investigating public records does not require reading QGIS's
generic Attribute Table.

It is a view, not a second data store: rows are built from the features of the
existing QGIS layer, each row keeps its QgsFeature id, and selecting a row
selects that feature on the real layer. Nothing here fetches from the network,
and the layer stays the single source of truth. The display rows are
materialized once per dataset so search and sort stay responsive on the
24k-feature layers; they are rebuilt whenever the underlying layer changes.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import (
    QAbstractTableModel,
    QItemSelectionModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..core import layers as layer_helpers

_GEOM_A, _GEOM_B = "@site_a", "@site_b"
_GEOM_LAT, _GEOM_LON = "@lat", "@lon"

# Curated columns per dataset, using the field names the production sources
# actually produce -- no invented fields.
COLUMNS = {
    layer_helpers.SOURCE_FIXED_LINKS: [
        ("Authorization", "authorization_number"), ("Licensee", "licensee"),
        ("Site A", _GEOM_A), ("Site B", _GEOM_B),
        ("Frequency (MHz)", "frequencies_mhz"), ("In service", "in_service_date"),
        ("Source", "source"),
    ],
    layer_helpers.SOURCE_FIXED_SITES: [
        ("Site", "name"), ("Licensee", "licensee"), ("Authorizations", "authorizations"),
        ("Call sign(s)", "call_signs"), ("Frequency (MHz)", "frequencies_mhz"),
        ("Province", "province"), ("Latitude", _GEOM_LAT), ("Longitude", _GEOM_LON),
        ("Source", "source"),
    ],
    layer_helpers.SOURCE_TOWERS: [
        ("Name", "name"), ("Type", "feature_type"), ("Record ID", "record_id"),
        ("Height AGL (m)", "height_above_ground_m"), ("Call sign", "radio_call_sign"),
        ("Purpose", "purpose"), ("Latitude", _GEOM_LAT), ("Longitude", _GEOM_LON),
        ("Source", "source"),
    ],
    layer_helpers.SOURCE_CELLULAR: [
        ("Licensee / location", "name"), ("Licensee", "licensee"), ("Service bands", "service_bands"),
        ("Channels", "channel_count"), ("Record ID", "record_id"),
        ("Latitude", _GEOM_LAT), ("Longitude", _GEOM_LON), ("Source", "source"),
    ],
    layer_helpers.SOURCE_SATELLITES: [
        ("Name", "name"), ("NORAD", "norad_cat_id"), ("Orbit", "orbit_category"),
        ("Period (min)", "period_minutes"), ("Altitude (km)", "altitude_km"),
        ("TLE epoch", "tle_epoch"), ("Sub-point lat", _GEOM_LAT), ("Sub-point lon", _GEOM_LON),
        ("Source", "source"),
    ],
    layer_helpers.SOURCE_GROUND_STATIONS: [
        ("Station", "name"), ("Owner", "licensee"), ("Status", "status"),
        ("Frequencies (MHz)", "frequencies_mhz"), ("Observations", "observations"),
        ("Altitude (m)", "altitude_m"), ("Latitude", _GEOM_LAT), ("Longitude", _GEOM_LON),
        ("Source", "source"),
    ],
}

# Which single-feature drawer a row of each dataset opens.
KINDS = {
    layer_helpers.SOURCE_FIXED_LINKS: "link",
    layer_helpers.SOURCE_FIXED_SITES: "site",
    layer_helpers.SOURCE_TOWERS: "site",
    layer_helpers.SOURCE_CELLULAR: "site",
    layer_helpers.SOURCE_SATELLITES: "satellite",
    layer_helpers.SOURCE_GROUND_STATIONS: "ground-station",
}

DATASET_ORDER = [
    layer_helpers.SOURCE_FIXED_LINKS, layer_helpers.SOURCE_FIXED_SITES,
    layer_helpers.SOURCE_TOWERS, layer_helpers.SOURCE_CELLULAR,
    layer_helpers.SOURCE_SATELLITES, layer_helpers.SOURCE_GROUND_STATIONS,
]

DATASET_LABELS = {
    layer_helpers.SOURCE_FIXED_LINKS: "Fixed Service links",
    layer_helpers.SOURCE_FIXED_SITES: "Fixed Service sites",
    layer_helpers.SOURCE_TOWERS: "Tower structures",
    layer_helpers.SOURCE_CELLULAR: "Cellular / mobile sites",
    layer_helpers.SOURCE_SATELLITES: "Satellites",
    layer_helpers.SOURCE_GROUND_STATIONS: "Ground / Earth stations",
}


def _format(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.5f}" if abs(value) < 1000 else f"{value:.2f}"
    return str(value)


def display_row(feature, columns) -> list:
    """The curated display values for one feature. Shared by the Records table
    and the selection summary so a record reads identically in both."""
    geom = feature.geometry()
    point = a_pt = b_pt = None
    if geom is not None and not geom.isEmpty():
        if geom.type() == 1:  # line
            line = geom.asMultiPolyline()[0] if geom.isMultipart() else geom.asPolyline()
            if line:
                a_pt, b_pt = line[0], line[-1]
        else:
            point = geom.centroid().asPoint()
    names = set(feature.fields().names())
    row = []
    for _, key in columns:
        if key == _GEOM_LAT:
            row.append(_format(point.y()) if point else "")
        elif key == _GEOM_LON:
            row.append(_format(point.x()) if point else "")
        elif key == _GEOM_A:
            row.append(f"{a_pt.y():.5f}, {a_pt.x():.5f}" if a_pt else "")
        elif key == _GEOM_B:
            row.append(f"{b_pt.y():.5f}, {b_pt.x():.5f}" if b_pt else "")
        else:
            row.append(_format(feature[key]) if key in names else "")
    return row


class RecordsModel(QAbstractTableModel):
    """Display rows for one Velorona layer, each carrying its QgsFeature id."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns = []
        self._rows = []   # list[list[str]]
        self._fids = []   # parallel list[int]

    def load(self, layer, source_key):
        self.beginResetModel()
        self._columns = COLUMNS.get(source_key, [])
        self._rows, self._fids = [], []
        if layer is not None and self._columns:
            for feature in layer.getFeatures():
                self._rows.append(display_row(feature, self._columns))
                self._fids.append(feature.id())
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        return self._rows[index.row()][index.column()]

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._columns[section][0]
        return section + 1

    def feature_id(self, row):
        return self._fids[row] if 0 <= row < len(self._fids) else None

    def row_for_feature(self, fid):
        try:
            return self._fids.index(fid)
        except ValueError:
            return -1


class VeloronaRecordsTable(QWidget):
    """Dataset picker + search + table. Emits the selected feature so the
    plugin can select it on the map and open the evidence drawer."""

    featureChosen = pyqtSignal(object, int, str)      # layer, feature id, kind
    featuresChosen = pyqtSignal(object, list, str)    # layer, feature ids, kind
    licenseeChanged = pyqtSignal(str)                 # '' means every licensee

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layers = {}       # source_key -> QgsVectorLayer
        self._current_key = None
        # The authoritative active operator, set by set_active_operator()
        # rather than read back off self.licensee_combo.currentData(): the
        # combo only reflects a filter that was CHOSEN THROUGH IT, and
        # plugin.set_licensee_filter() is not exclusively driven by the
        # combo's own signal (multi-record export and other callers can also
        # set it). Reading the combo directly would leave the empty-state
        # message wrong -- or silent -- for any filter applied that way.
        self._active_operator = ""
        self._syncing = False

        self.dataset_combo = QComboBox(self)
        # Operator filter across every layer that carries a 'licensee' field
        # (Fixed Service sites, Fixed Service links, Cellular sites -- see
        # layer_helpers.OPERATOR_SOURCE_KEYS). The list is built from the
        # loaded records -- no operator is hard-coded -- and choosing one
        # filters those layers in place, so the map clusters, this table and
        # any selection/export see the same subset without a new request.
        #
        # Visible from the moment this widget is constructed, i.e. as soon as
        # the Velorona dock opens -- never hidden behind picking a particular
        # dataset tab, the way it used to be (shown only when Fixed Service
        # sites happened to be selected). It starts disabled, with an empty
        # list, until populate_licensees() has real counts to show; disabled
        # communicates "not ready yet" without making the control disappear
        # and reappear as the operator switches tabs.
        self.operator_label = QLabel("Operator", self)
        self.licensee_combo = QComboBox(self)
        self.licensee_combo.setEditable(True)
        self.licensee_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.licensee_combo.lineEdit().setPlaceholderText("Filter by operator...")
        self.licensee_combo.setToolTip(
            "Show only this operator's records across Fixed Service sites, Fixed Service "
            "links and Cellular sites. Counts are record counts.")
        self.licensee_combo.setEnabled(False)
        self.licensee_combo.addItem("Load Public Data to populate", "")
        # Web Map parity: "N operator(s) from currently-loaded data"
        # (aei-link-clearance/web/app.js: refreshOperatorDropdown()).
        self.operator_hint = QLabel("", self)
        self.operator_hint.setObjectName("veloronaOperatorHint")
        self.operator_hint.setVisible(False)
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Search records...")
        self.search_edit.setClearButtonEnabled(True)
        self.status_label = QLabel("Run Explore: Load Public Data to populate records.", self)
        self.status_label.setObjectName("veloronaRecordsStatus")

        self.model = RecordsModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)  # search every column

        self.view = QTableView(self)
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setAlternatingRowColors(True)
        self.view.verticalHeader().setVisible(False)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.view.horizontalHeader().setStretchLastSection(True)
        # Measure only a sample of rows when sizing columns; measuring all
        # 24k rows would make every dataset switch visibly slow.
        self.view.horizontalHeader().setResizeContentsPrecision(40)

        top = QHBoxLayout()
        top.addWidget(self.dataset_combo, 1)
        top.addWidget(self.search_edit, 2)
        operator_row = QHBoxLayout()
        operator_row.addWidget(self.operator_label)
        operator_row.addWidget(self.licensee_combo, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(top)
        layout.addLayout(operator_row)
        layout.addWidget(self.operator_hint)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.status_label)

        self.dataset_combo.currentIndexChanged.connect(self._on_dataset_changed)
        self.licensee_combo.currentIndexChanged.connect(self._on_licensee_changed)
        self.search_edit.textChanged.connect(self._on_search)
        self.view.selectionModel().selectionChanged.connect(self._on_row_selected)

    # -- population -----------------------------------------------------

    def set_layers(self, layers_by_key: dict) -> None:
        """Point the table at the Velorona layers currently in the project."""
        self._layers = {k: v for k, v in layers_by_key.items() if v is not None and k in COLUMNS}
        previous = self._current_key
        self.dataset_combo.blockSignals(True)
        self.dataset_combo.clear()
        for key in DATASET_ORDER:
            if key in self._layers:
                self.dataset_combo.addItem(DATASET_LABELS[key], key)
        self.dataset_combo.blockSignals(False)
        if self.dataset_combo.count() == 0:
            self.model.load(None, None)
            self.status_label.setText("Run Explore: Load Public Data to populate records.")
            return
        index = max(0, self.dataset_combo.findData(previous))
        self.dataset_combo.setCurrentIndex(index)
        self._on_dataset_changed(index)

    def _on_dataset_changed(self, _index):
        key = self.dataset_combo.currentData()
        if key is None:
            return
        self._current_key = key
        self.model.load(self._layers.get(key), key)
        self.view.resizeColumnsToContents()
        self._update_status()
        # The Operator combo itself stays visible and enabled regardless of
        # which dataset tab is showing: it is a map-wide filter (Fixed
        # Service sites, Fixed Service links and Cellular sites all filter
        # together, see plugin.set_licensee_filter), not a per-tab control.

    def populate_licensees(self, counts) -> None:
        """Fills the filter from the operator values actually present in the
        loaded records (Fixed Service sites, Fixed Service links, Cellular
        sites combined -- see plugin._operator_counts()), most records
        first, and enables the control now that it has something real to
        offer."""
        current = self.licensee_combo.currentData()
        self.licensee_combo.blockSignals(True)
        self.licensee_combo.clear()
        total = sum(counts.values())
        self.licensee_combo.addItem(f"All operators ({total:,} records)", "")
        for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            self.licensee_combo.addItem(f"{name} ({count:,})", name)
        index = self.licensee_combo.findData(current) if current else 0
        self.licensee_combo.setCurrentIndex(max(0, index))
        self.licensee_combo.blockSignals(False)
        self.licensee_combo.setEnabled(bool(counts))
        self.operator_hint.setText(f"{len(counts):,} operator(s) from currently-loaded data.")
        self.operator_hint.setVisible(bool(counts))

    def _on_licensee_changed(self, _index):
        self.licenseeChanged.emit(self.licensee_combo.currentData() or "")

    def current_source_key(self) -> str:
        return self._current_key or ""

    def set_active_operator(self, licensee: str) -> None:
        """Records which operator is actually applied right now, so the
        empty-state message stays correct regardless of whether this filter
        came from the combo or from elsewhere (plugin.set_licensee_filter()
        is called wherever the active filter changes, not only from
        _on_licensee_changed below)."""
        self._active_operator = licensee or ""
        self._update_status()

    def refresh_current(self) -> None:
        """Rebuild the visible dataset from its layer (used after the viewport
        layers fetch new features)."""
        if self._current_key:
            self.model.load(self._layers.get(self._current_key), self._current_key)
            self._update_status()

    def _on_search(self, text):
        self.proxy.setFilterFixedString(text)
        self._update_status()

    def _update_status(self):
        total = self.model.rowCount()
        shown = self.proxy.rowCount()
        operator = self._active_operator
        if total == 0:
            # Distinguish "nothing loaded yet" from "the Operator filter
            # legitimately matches nothing here" -- a blank table with no
            # explanation reads as broken, not as an accurate empty result.
            # Only datasets the Operator filter actually applies to
            # (layer_helpers.OPERATOR_SOURCE_KEYS) get the filter-specific
            # message; Towers/Satellites/Ground Stations carry no licensee
            # field, so an active filter chosen while viewing Fixed Service
            # never gets blamed for an unrelated dataset being unloaded.
            if operator and self._current_key in layer_helpers.OPERATOR_SOURCE_KEYS:
                self.status_label.setText(
                    f"No records match operator “{operator}” in this dataset. "
                    f"Clear the Operator filter to see everything.")
            else:
                self.status_label.setText("No records in this dataset yet.")
        elif shown == total:
            self.status_label.setText(f"{total:,} records")
        else:
            self.status_label.setText(f"{shown:,} of {total:,} records")

    # -- selection ------------------------------------------------------

    def _on_row_selected(self, *_):
        if self._syncing:
            return
        indexes = self.view.selectionModel().selectedRows()
        layer = self._layers.get(self._current_key)
        if layer is None or not indexes:
            return
        kind = KINDS.get(self._current_key, "site")
        fids = [fid for fid in
                (self.model.feature_id(self.proxy.mapToSource(i).row()) for i in indexes)
                if fid is not None]
        if not fids:
            return
        if len(fids) == 1:
            self.featureChosen.emit(layer, fids[0], kind)
        else:
            self.featuresChosen.emit(layer, fids, kind)

    def show_features(self, layer, fids) -> None:
        """Highlight several rows for a multi-feature map selection, without
        echoing the change back as a new selection."""
        key = layer_helpers.layer_source_key(layer)
        if key not in self._layers:
            return
        self._syncing = True
        try:
            if key != self._current_key:
                index = self.dataset_combo.findData(key)
                if index >= 0:
                    self.dataset_combo.setCurrentIndex(index)
            selection_model = self.view.selectionModel()
            selection_model.clearSelection()
            wanted = set(fids)
            first = None
            # Select (not selectRow): selectRow replaces the current selection,
            # so extending it row by row would leave only the last one.
            flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
            for row in range(self.model.rowCount()):
                if self.model.feature_id(row) in wanted:
                    proxy_index = self.proxy.mapFromSource(self.model.index(row, 0))
                    if proxy_index.isValid():
                        selection_model.select(proxy_index, flags)
                        first = first or proxy_index
            if first is not None:
                self.view.scrollTo(first, QAbstractItemView.ScrollHint.PositionAtCenter)
        finally:
            self._syncing = False

    def show_feature(self, layer, fid) -> None:
        """Highlight the row for a feature selected on the map, switching
        dataset if that feature belongs to another Velorona layer."""
        key = layer_helpers.layer_source_key(layer)
        if key not in self._layers:
            return
        self._syncing = True
        try:
            if key != self._current_key:
                index = self.dataset_combo.findData(key)
                if index >= 0:
                    self.dataset_combo.setCurrentIndex(index)
            row = self.model.row_for_feature(fid)
            if row < 0:
                return
            proxy_index = self.proxy.mapFromSource(self.model.index(row, 0))
            if not proxy_index.isValid():
                return
            self.view.selectRow(proxy_index.row())
            self.view.scrollTo(proxy_index, QAbstractItemView.ScrollHint.PositionAtCenter)
        finally:
            self._syncing = False
