"""
Habitat Network Analysis Tool
Copyright (C) 2023  Martin Fitger, Oskar Kindvall, Ioanna Stavroulaki, Meta Berghauser Pont

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

from builtins import object
from qgis.core import QgsApplication
from .processing import HabitatConnectivityToolProcessingProvider

class HabitatConnectivityToolPlugin(object):

	def __init__(self, iface):
		self.iface = iface  # Save reference to the QGIS interface

	def initGui(self):
		self.initProcessing()

	def unload(self):
		self.uninitProcessing()

	def initProcessing(self):
		self._processingProvider = HabitatConnectivityToolProcessingProvider()
		QgsApplication.processingRegistry().addProvider(self._processingProvider)

	def uninitProcessing(self):
		if self._processingProvider is not None:
			QgsApplication.processingRegistry().removeProvider(self._processingProvider)
			self._processingProvider = None