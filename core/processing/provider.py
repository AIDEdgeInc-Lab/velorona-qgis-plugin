from __future__ import annotations

from qgis.core import QgsProcessingProvider

from .terrain_batch import TerrainClearanceBatch

PROVIDER_ID = "velorona"


class VeloronaProcessingProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(TerrainClearanceBatch())

    def id(self):
        return PROVIDER_ID

    def name(self):
        return "Velorona"

    def longName(self):
        return "Velorona -- telecom link evidence"
