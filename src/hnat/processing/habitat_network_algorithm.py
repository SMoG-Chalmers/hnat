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

import math, os
from qgis.PyQt.QtCore import (QCoreApplication,
							  QSettings)
from qgis.PyQt.QtGui import QColor
from qgis import processing
from qgis.core import (QgsColorRampShader,
					   QgsLayerTreeGroup,
					   QgsProcessing,
					   QgsProcessingAlgorithm,
					   QgsProcessingContext,
					   QgsProcessingUtils,
					   QgsProcessingParameterRasterLayer,
					   QgsProcessingParameterFile,
					   QgsProcessingParameterFolderDestination,
					   QgsRasterBandStats,
					   QgsRasterLayer,
					   QgsRasterShader,
					   QgsSingleBandPseudoColorRenderer,
					   )
from ..xl import OpenWorkbook
from .utils import GetBackwardsCompatiblePath
from qgis.utils import iface


def CellRef(x, y):
	return chr(ord('A') + x) + str(y + 1)


class BatchParameters:
	BIOTOPE_CODE_HDR = 'BiotopeCode'

	def __init__(self, biotopeCodes, parameterSets):
		self.biotopeCodes = biotopeCodes
		self.parameterSets = parameterSets


class ParameterSet:
	# Parameters
	NAME_PARAM = 'Network name'
	DISPERSAL_PARAM = 'Average dispersal distance (metres)'
	NETWORK_THRESHOLD_PARAM = ['Network threshold', 'Minimum dispersal probability']
	PARAMS = [NAME_PARAM, DISPERSAL_PARAM, NETWORK_THRESHOLD_PARAM] 
	# Columns
	QUALITY_COLUMN = 'Quality'
	SOURCE_COLUMN = ['Source', 'Reproduction']
	FRICTION_COLUMN = 'Friction'
	COLUMNS = [QUALITY_COLUMN, SOURCE_COLUMN, FRICTION_COLUMN]

	def __init__(self, parameters, columns):
		self.parameters = parameters
		self.columns = columns

	def parameter(self, name_or_nameList):
		names = name_or_nameList if isinstance(name_or_nameList, list) else [name_or_nameList]
		for name in names:
			value = self.parameters.get(name)
			if value is not None:
				return value
		raise Exception("Missing parameter '%s'." % name[0])

	def column(self, name_or_nameList):
		names = name_or_nameList if isinstance(name_or_nameList, list) else [name_or_nameList]
		for name in names:
			column = self.columns.get(name)
			if column is not None:
				return column
		raise Exception("Missing parameter set column '%s'." % name[0])


class HabitatNetworkAlgorithm(QgsProcessingAlgorithm):

	# Parameters
	BIOTOPE_RASTER = 'BIOTOPE_RASTER'
	PARAMETER_TABLE_FILE = 'PARAMETER_TABLE_FILE'
	DISPERSAL_THRESHOLD = 'DISPERSAL_THRESHOLD'
	MEAN_MIGRATION_DISTANCE = 'MEAN_MIGRATION_DISTANCE'
	OUTPUT_FOLDER = 'OUTPUT_FOLDER'

	GREEN_YELLOW_RED_RAMP = [
		QColor(26,150,65),
		QColor(166,217,106),
		QColor(255,255,192),
		QColor(253,174,97),
		QColor(215,25,28)
	]

	RED_YELLOW_GREEN_RAMP = [
		QColor(215,25,28),
		QColor(253,174,97),
		QColor(255,255,192),
		QColor(166,217,106),
		QColor(26,150,65)
	]

	BLUE_GREEN_YELLOW_RED_RAMP = [
		QColor(43,131,186),
		QColor(171,221,164),
		QColor(255,255,191),
		QColor(253,174,97),
		QColor(215,25,28)
	]

	YELLOW_BLUE_RAMP = [
		QColor(255,255,204),
		QColor(161,218,180),
		QColor(65,182,196),
		QColor(44,127,184),
		QColor(37,52,148)
	]

	YELLOW_RED_RAMP = [
		QColor(255,255,191),
		QColor(253,174,97),
		QColor(215,25,28)
	]

	def initAlgorithm(self, config):

		settings = QSettings()

		self._outputFolder = None
		self._outputSubPath = None
		
		self._layers = []

		self.addParameter(
			QgsProcessingParameterRasterLayer(
				self.BIOTOPE_RASTER,
				self.tr('Biotope Raster Layer')
			)
		)

		self.addParameter(
			QgsProcessingParameterFile(
				self.PARAMETER_TABLE_FILE,
				self.tr('Parameter Table File'),
				defaultValue = settings.value(self._generateSettingsKey(self.PARAMETER_TABLE_FILE), None),
				fileFilter = 'Excel workbook (*.xlsx)'
			)
		)

		self.addParameter(
			QgsProcessingParameterFolderDestination(
				self.OUTPUT_FOLDER,
				self.tr('Output folder'),
				defaultValue = settings.value(self._generateSettingsKey(self.OUTPUT_FOLDER), None)
			)
		)

	def checkParameterValues(self, parameters, context):
		props = self._collectProperties(parameters, context)

		#return (False, "No radius specified")
		return (True, None)

	def _generateSettingsKey(self, name):
		return "psteco/habitat_network/" + name

	def processAlgorithm(self, parameters, context, feedback):
		try:
			self._processingContext = context

			props = self._collectProperties(parameters, context)

			settings = QSettings()
			settings.setValue(self._generateSettingsKey(self.PARAMETER_TABLE_FILE), props[self.PARAMETER_TABLE_FILE])
			settings.setValue(self._generateSettingsKey(self.OUTPUT_FOLDER), props[self.OUTPUT_FOLDER])

			# Output folder
			self._setOutputFolder(props[self.OUTPUT_FOLDER])
			self._setOutputSubPath(None)
			self._setOutputPrefix(None)

			feedback.pushInfo("Loading parameters from '%s'..." % (props[self.PARAMETER_TABLE_FILE]))
			batchParameters = self._loadBatchParameters(props[self.PARAMETER_TABLE_FILE], feedback)

			feedback.pushInfo("Found %d parameter sets: %s" % (len(batchParameters.parameterSets), [parameterSet.parameter(ParameterSet.NAME_PARAM) for parameterSet in batchParameters.parameterSets]))

			for parameterSet in batchParameters.parameterSets:
				feedback.pushInfo("parameters: " + str(parameterSet.parameters))
				feedback.pushInfo("columns: " + str(parameterSet.columns))

			for parameterSetIndex, parameterSet in enumerate(batchParameters.parameterSets):
				feedback.pushInfo("\nProcessing parameter set '%s'..." % parameterSet.parameters[ParameterSet.NAME_PARAM])
				self._setOutputSubPath(parameterSet.parameters[ParameterSet.NAME_PARAM])
				self._setOutputPrefix(parameterSet.parameters[ParameterSet.NAME_PARAM] + ' - ')

				source_raster = self._createSourceRaster(context, 'Source Raster', props[self.BIOTOPE_RASTER], batchParameters.biotopeCodes, parameterSet.column(ParameterSet.SOURCE_COLUMN), feedback)
				friction_raster = self._createFrictionRaster(context, 'Friction Raster', props[self.BIOTOPE_RASTER], batchParameters.biotopeCodes, parameterSet.column(ParameterSet.FRICTION_COLUMN), feedback)
				quality_raster = self._createQualityRaster(context, 'Quality Raster', props[self.BIOTOPE_RASTER], batchParameters.biotopeCodes, parameterSet.column(ParameterSet.QUALITY_COLUMN), feedback)
				costdistance_raster = self._createCostDistanceRaster(context, 'Cost-Distance Raster', source_raster, friction_raster, parameterSet.parameter(ParameterSet.DISPERSAL_PARAM), parameterSet.parameter(ParameterSet.NETWORK_THRESHOLD_PARAM), feedback)
				dispersal_raster = self._createDispersalRaster(context, 'Dispersal Raster', costdistance_raster, parameterSet.parameter(ParameterSet.DISPERSAL_PARAM), feedback)
				functionality_raster = self._createFunctionalityRaster(context, 'Functionality Raster', dispersal_raster, quality_raster, feedback)

				self._addLayer(source_raster, self._outputSubPath)
				self._addLayer(functionality_raster, self._outputSubPath)
				self._addLayer(dispersal_raster, self._outputSubPath)
				self._addLayer(quality_raster, self._outputSubPath)
				self._addLayer(costdistance_raster, self._outputSubPath)
				self._addLayer(friction_raster, self._outputSubPath)

			return {}
		finally:
			self._processingContext = None

	def postProcessAlgorithm(self, context, feedback):

		feedback.pushInfo("Post processing...")

		project = context.project()

		root = project.instance().layerTreeRoot()

		# If a group is selected, then use that as root
		selected_nodes = ( iface.layerTreeView().selectedNodes() )
		if selected_nodes and isinstance(selected_nodes[0], QgsLayerTreeGroup):
			root = selected_nodes[0]

		project.addMapLayers([layer_data[0] for layer_data in self._layers], False)

		# Create layer group nodes
		group_nodes = {}
		count_per_group = {}
		count_at_root = 0
		for layer, group_name in self._layers:
			if group_name:
				group = group_nodes.get(group_name)
				if group is None:
					group = root.insertGroup(len(group_nodes), group_name)
					# For some reason we need to first explicitly set the group node to 
					# NOT EXPANDED in order to make the expand loop below have effect.
					group.setExpanded(False)
					group_nodes[group_name] = group
					count_per_group[group_name] = 0
				index = count_per_group[group_name]
				count_per_group[group_name] = index + 1
				layer_node = group.insertLayer(int(index), layer)
				layer_node.setExpanded(False)
			else:
				root.insertLayer(count_at_root, layer)
				count_at_root = count_at_root + 1
		
		# Expand group nodes
		for group_node in group_nodes.values():
			group_node.setExpanded(True)

		self._layers = []

	def _setOutputFolder(self, path):
		self._outputFolder = self._tempFolder() if 'TEMPORARY_OUTPUT' == path else path

	def _setOutputSubPath(self, subPath):
		if subPath:
			full_path = os.path.join(self._outputFolder, subPath)
			if not os.path.exists(full_path):
				os.makedirs(full_path)
		self._outputSubPath = subPath

	def _setOutputPrefix(self, prefix):
		self._outputPrefix = prefix

	def _tempFolder(self):
		return QgsProcessingUtils.tempFolder()

	def _getTempPath(self, fileName):
		return os.path.join(GetBackwardsCompatiblePath(self._tempFolder()), fileName)

	def _getOutputPath(self, fileName):
		path = self._outputFolder
		if self._outputSubPath:
			path = os.path.join(path, self._outputSubPath)
		if self._outputPrefix:
			fileName = self._outputPrefix + fileName
		return os.path.join(GetBackwardsCompatiblePath(path), fileName)

	def _loadBatchParameters(self, path, feedback):
		workbook = OpenWorkbook(path)
		sheet_index = 0
		feedback.pushInfo("Loading parameters from sheet #%d ('%s')..." %(sheet_index + 1, workbook.sheetName(sheet_index)))
		rows = workbook.loadSheetData(sheet_index)

		# Find index of table header row
		headerRowIndex = None
		for i,row in enumerate(rows):
			if BatchParameters.BIOTOPE_CODE_HDR in row:
				headerRowIndex = i
				break
		if not headerRowIndex:
			raise Exception('Column header "%s" not found.' % BatchParameters.BIOTOPE_CODE_HDR)
		headerRow = rows[headerRowIndex]

		# Find row headers by looking for network name row header
		headerColumnIndex = None
		for row_index in range(headerRowIndex):
			row = rows[row_index]
			for column_index in range(len(row)):
				if row[column_index] == ParameterSet.PARAMS[0]:
					headerColumnIndex = column_index
					break
			if headerColumnIndex:
				break
		if not headerColumnIndex:
			raise Exception('Row header "%s" not found.' % ParameterSet.PARAMS[0])
		header_to_row_map = {}
		for row_index in range(headerRowIndex):
			row = rows[row_index]
			if len(row) >= headerColumnIndex:
				header_name = row[headerColumnIndex]
				if header_name:
					header_to_row_map[header_name] = row_index

		# Read biotope codes
		biotopeCodes = self.columnValues(rows, headerRow.index(BatchParameters.BIOTOPE_CODE_HDR), headerRowIndex + 1, len(rows) - headerRowIndex - 1)

		# Row headers
		for row_header_or_headers in ParameterSet.PARAMS:
			row = None
			row_headers = row_header_or_headers if isinstance(row_header_or_headers, list) else [row_header_or_headers]
			for header in row_headers:
				row = header_to_row_map.get(header)
				if row is not None:
					break
			if row is None:
				if len(row_headers) == 1:
					err_msg = 'Row header "%s" not found.' % row_headers[0]
				else:
					err_msg = 'None of the following row headers were found: "%s"' % '", "'.join(row_headers)
				raise Exception(err_msg)

		# Read parameter sets
		parameterSets = []
		current_column_index = headerColumnIndex + 1
		network_name_row = rows[header_to_row_map[ParameterSet.NAME_PARAM]]
		while current_column_index < len(network_name_row) and current_column_index < len(headerRow) and headerRow[current_column_index]:
			parameters = {}
			for param,row_index in header_to_row_map.items():
				row = rows[row_index]
				value = row[current_column_index] if current_column_index < len(row) else None
				if not value:
					raise Exception("Expected %s value in cell %s" % (param, CellRef(current_column_index, row_index)))
				parameters[param] = value
				name_row = rows[header_to_row_map[ParameterSet.NAME_PARAM]]
			columns = {}
			while current_column_index < len(headerRow) and headerRow[current_column_index]:
				columns[headerRow[current_column_index]] = self.columnValues(rows, current_column_index, headerRowIndex + 1, len(biotopeCodes))
				current_column_index = current_column_index + 1
				if current_column_index >= len(name_row) or name_row[current_column_index]:
					break

			# Verify all columns are present
			for column_name_or_names in ParameterSet.COLUMNS:
				column_names = column_name_or_names if isinstance(column_name_or_names, list) else [column_name_or_names]
				column = None
				for name in column_names:
					column = columns.get(name)
					if column is not None:
						break
				if column is None:
					if len(column_names) == 1:
						err_msg = 'Column "%s" not found for network "%s".' % (column_names[0], parameters[ParameterSet.NAME_PARAM])
					else:
						err_msg = 'None of the following columns were found for network "%s": "%s"' % (parameters[ParameterSet.NAME_PARAM], '", "'.join(column_names))
					raise Exception(err_msg)

			parameterSets.append(ParameterSet(parameters, columns))

		return BatchParameters(biotopeCodes, parameterSets)

	def columnValues(self, rows, column_index, first_row, row_count):
		values = []
		for i in range(row_count):
			row = rows[first_row + i]
			if column_index >= len(row) or (not row[column_index] and 0 != row[column_index]):
				raise Exception("Value expected in cell %s" % CellRef(column_index, first_row + i))
			values.append(row[column_index])
		return values

	def _createSourceRaster(self, context, title, biotope_raster, biotope_codes, reproduction_values, feedback):
		feedback.pushInfo("\nCreating source raster layer...")
		reproduction_biotope_codes = [biotope_codes[i] for i in range(len(reproduction_values)) if reproduction_values[i] == 1]
		feedback.pushInfo("Reproduction biotope codes: " + str(reproduction_biotope_codes))
		conditions = ')+('.join(['A==%d' % code for code in reproduction_biotope_codes])
		formula = '((%s))*1' % conditions
		rastercalculator_input = {
			'INPUT_A':biotope_raster,
			'BAND_A':1,
			'INPUT_B':None,
			'BAND_B':None,
			'INPUT_C':None,
			'BAND_C':None,
			'INPUT_D':None,
			'BAND_D':None,
			'INPUT_E':None,
			'BAND_E':None,
			'INPUT_F':None,
			'BAND_F':None,
			'FORMULA':formula,
			'NO_DATA':0,  
			'PROJWIN':None,
			'RTYPE':0,  # BYTE
			'OPTIONS':'',
			'EXTRA':'',
			'OUTPUT':self._getOutputPath(title + '.tif')
		}

		feedback.pushInfo("Input to gdal:rastercalculator:\n" + str(rastercalculator_input))

		rastercalculator_output = processing.run("gdal:rastercalculator", rastercalculator_input)

		feedback.pushInfo("Output from gdal:rastercalculator:\n" + str(rastercalculator_output))

		output_layer_path = rastercalculator_output['OUTPUT']
		output_layer = QgsRasterLayer(output_layer_path)
		output_layer.setName(title)

		return output_layer

	def _createFrictionRaster(self, context, title, biotope_raster, biotope_codes, friction_values, feedback):
		feedback.pushInfo("\nCreating friction raster layer...")
		formula = '+'.join(['(A==%d)*%f' % (biotope_codes[i], friction_values[i]) for i in range(len(friction_values)) if friction_values[i] > 0])
		rastercalculator_input = {
			'INPUT_A':biotope_raster,
			'BAND_A':1,
			'INPUT_B':None,
			'BAND_B':None,
			'INPUT_C':None,
			'BAND_C':None,
			'INPUT_D':None,
			'BAND_D':None,
			'INPUT_E':None,
			'BAND_E':None,
			'INPUT_F':None,
			'BAND_F':None,
			'FORMULA':formula,
			'NO_DATA':-1,
			'PROJWIN':None,
			'RTYPE':5, # FLOAT32
			'OPTIONS':'',
			'EXTRA':'',
			'OUTPUT':self._getOutputPath(title + '.tif')
		}

		feedback.pushInfo("Input to gdal:rastercalculator:\n" + str(rastercalculator_input))

		rastercalculator_output = processing.run("gdal:rastercalculator", rastercalculator_input)

		feedback.pushInfo("Output from gdal:rastercalculator:\n" + str(rastercalculator_output))

		# Load layer
		output_layer_path = rastercalculator_output['OUTPUT']
		output_layer = QgsRasterLayer(output_layer_path)
		output_layer.setName(title)

		# Apply shader to raster
		self.setRampShader(output_layer, None, self.YELLOW_RED_RAMP)

		return output_layer

	def _createQualityRaster(self, context, title, biotope_raster, biotope_codes, quality_values, feedback):
		feedback.pushInfo("\nCreating quality raster layer...")
		formula = '+'.join(['(A==%d)*%d' % (biotope_codes[i], quality_values[i]) for i in range(len(quality_values)) if quality_values[i] > 0])
		rastercalculator_input = {
			'INPUT_A':biotope_raster,
			'BAND_A':1,
			'INPUT_B':None,
			'BAND_B':None,
			'INPUT_C':None,
			'BAND_C':None,
			'INPUT_D':None,
			'BAND_D':None,
			'INPUT_E':None,
			'BAND_E':None,
			'INPUT_F':None,
			'BAND_F':None,
			'FORMULA':formula,
			'NO_DATA':255,  
			'PROJWIN':None,
			'RTYPE':0,  # BYTE
			'OPTIONS':'',
			'EXTRA':'',
			'OUTPUT':self._getOutputPath(title + '.tif')
		}

		feedback.pushInfo("Input to gdal:rastercalculator:\n" + str(rastercalculator_input))

		rastercalculator_output = processing.run("gdal:rastercalculator", rastercalculator_input)

		feedback.pushInfo("Output from gdal:rastercalculator:\n" + str(rastercalculator_output))

		# Load layer
		output_layer_path = rastercalculator_output['OUTPUT']
		output_layer = QgsRasterLayer(output_layer_path)
		output_layer.setName(title)

		# Apply shader to raster
		self.setRampShader(output_layer, None, self.YELLOW_BLUE_RAMP)

		return output_layer

	def _createCostDistanceRaster(self, context, title, source_raster, friction_raster, mean_migration_distance, dispersal_threshold, feedback):

		feedback.pushInfo("\nCreating cost-distance raster layer...")

		max_value = math.ceil(-mean_migration_distance * math.log(dispersal_threshold))

		feedback.pushInfo("Maximum cost-distance: %.0f" % (max_value))

		const_distance_input = {
			'input':friction_raster,
			'start_coordinates':None,
			'stop_coordinates':None,
			'-k':False,
			'-n':True,
			'start_points':None,
			'stop_points':None,
			'start_raster':source_raster,
			'max_cost': max_value / 10,
			'null_cost': None,
			'memory':300,
			'output':self._getTempPath('cost_distance_intermediate.tif'),
			'nearest':'TEMPORARY_OUTPUT',
			'outdir':'TEMPORARY_OUTPUT',
			'GRASS_REGION_PARAMETER':None,
			'GRASS_REGION_CELLSIZE_PARAMETER':0,
			'GRASS_RASTER_FORMAT_OPT':'',
			'GRASS_RASTER_FORMAT_META':'',
			'GRASS_SNAP_TOLERANCE_PARAMETER':-1,
			'GRASS_MIN_AREA_PARAMETER':0.0001
		}
		feedback.pushInfo("Calling grass7:r.cost to calculate cost-distance...")
		feedback.pushInfo("input: " + str(const_distance_input))
		cost_distance_output = processing.run(
			"grass7:r.cost", 
			const_distance_input
		)

		feedback.pushInfo("grass7:r.cost output:\n" + str(cost_distance_output))

		output_title = title + (" max%dm" % max_value)

		feedback.pushInfo("\nCalling gdal:rastercalculator to post-process cost-dist output...")
		raster_calc_input = {
			'INPUT_A': cost_distance_output['output'],
			'BAND_A':1,
			'INPUT_B':None,
			'BAND_B':None,
			'INPUT_C':None,
			'BAND_C':None,
			'INPUT_D':None,
			'BAND_D':None,
			'INPUT_E':None,
			'BAND_E':None,
			'INPUT_F':None,
			'BAND_F':None,
			'FORMULA':'minimum(A*10, %f)' % (max_value),
			'NO_DATA':-1,
			'PROJWIN':None,
			'RTYPE':5,  # 5=Float32
			'OPTIONS':'',
			'EXTRA':'',
			'OUTPUT': self._getOutputPath(output_title + '.tif')
		}
		feedback.pushInfo("input: " + str(raster_calc_input))
		raster_calc_output = processing.run(
			"gdal:rastercalculator", 
			raster_calc_input
		)

		feedback.pushInfo("gdal:rastercalculator output:\n" + str(raster_calc_output))
		
		output_layer_path = raster_calc_output['OUTPUT']
		output_layer = QgsRasterLayer(output_layer_path)
		output_layer.setName(output_title)

		# Apply shader to raster
		self.setRampShader(output_layer, max_value, self.GREEN_YELLOW_RED_RAMP)

		return output_layer

	def _createDispersalRaster(self, context, title, costdistance_raster, average_dispersal_distance, feedback):

		feedback.pushInfo("\nCreating dispersal raster layer...")

		raster_calc_input = {
			'INPUT_A': costdistance_raster,
			'BAND_A':1,
			'INPUT_B':None,
			'BAND_B':None,
			'INPUT_C':None,
			'BAND_C':None,
			'INPUT_D':None,
			'BAND_D':None,
			'INPUT_E':None,
			'BAND_E':None,
			'INPUT_F':None,
			'BAND_F':None,
			'FORMULA':'exp(-A/%f)' % (average_dispersal_distance),
			'NO_DATA':0,
			'PROJWIN':None,
			'RTYPE':5,  # 5=Float32
			'OPTIONS':'',
			'EXTRA':'',
			'OUTPUT': self._getOutputPath(title + '.tif')
		}
		feedback.pushInfo("input: " + str(raster_calc_input))
		raster_calc_output = processing.run(
			"gdal:rastercalculator", 
			raster_calc_input
		)

		feedback.pushInfo("gdal:rastercalculator output:\n" + str(raster_calc_output))
		
		# Add Layer
		output_layer_path = raster_calc_output['OUTPUT']
		output_layer = QgsRasterLayer(output_layer_path)
		output_layer.setName(title)

		# Apply shader to raster
		self.setRampShader(output_layer, 1, self.RED_YELLOW_GREEN_RAMP)

		return output_layer

	def _createFunctionalityRaster(self, context, title, dispersal_raster, quality_raster, feedback):

		feedback.pushInfo("\nCreating habitat functionality raster layer...")

		raster_calc_input = {
			'INPUT_A': dispersal_raster,
			'BAND_A':1,
			'INPUT_B':quality_raster,
			'BAND_B':1,
			'INPUT_C':None,
			'BAND_C':None,
			'INPUT_D':None,
			'BAND_D':None,
			'INPUT_E':None,
			'BAND_E':None,
			'INPUT_F':None,
			'BAND_F':None,
			'FORMULA':'A*B',
			'NO_DATA':-1,
			'PROJWIN':None,
			'RTYPE':5,  # 5=Float32
			'OPTIONS':'',
			'EXTRA':'',
			'OUTPUT': self._getTempPath('functionality_with_null.tif'),
		}
		feedback.pushInfo("input: " + str(raster_calc_input))
		raster_calc_output = processing.run(
			"gdal:rastercalculator", 
			raster_calc_input
		)

		feedback.pushInfo("gdal:rastercalculator output:\n" + str(raster_calc_output))
		

		feedback.pushInfo("\nConverting NULL -> ZERO in functionality raster...")
		null_output = processing.run("grass7:r.null", {
			'map': raster_calc_output['OUTPUT'],
			'setnull':'',
			'null':0,
			'-f':False,
			'-i':False,
			'-n':False,
			'-c':False,
			'-r':False,
			'output': self._getOutputPath(title + '.tif'),
			'GRASS_REGION_PARAMETER':None,
			'GRASS_REGION_CELLSIZE_PARAMETER':0,
			'GRASS_RASTER_FORMAT_OPT':'',
			'GRASS_RASTER_FORMAT_META':''
		})

		feedback.pushInfo("grass7:r.null output:\n" + str(null_output))

		# Add Layer
		output_layer_path = null_output['output']
		output_layer = QgsRasterLayer(output_layer_path)
		output_layer.setName(title)

		# Apply shader to raster
		self.setRampShader(output_layer, None, self.BLUE_GREEN_YELLOW_RED_RAMP)
		
		return output_layer

	def setRampShader(self, layer, max_value, colors):
		if max_value is None:
			stats = layer.dataProvider().bandStatistics(1, QgsRasterBandStats.Max, layer.extent(), 0)
			max_value = stats.maximumValue
		shader = QgsRasterShader()
		fnc = QgsColorRampShader()
		fnc.setColorRampType(QgsColorRampShader.Interpolated)
		ramp_items = [QgsColorRampShader.ColorRampItem(i * max_value / (len(colors) - 1), colors[i]) for i in range(len(colors))]
		fnc.setColorRampItemList(ramp_items)
		shader.setRasterShaderFunction(fnc)
		renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
		renderer.setClassificationMin(0)
		renderer.setClassificationMax(max_value)
		layer.setRenderer(renderer)

	def _getColumnValues(self, rows, column_name, header_row_index, feedback = None):
		column_index = None
		for i, text in enumerate(rows[header_row_index]):
			if text == column_name:
				column_index = i
				break
		if column_index is None:
			raise Exception("Column '%s' not found" % column_name)
		values = [rows[i+header_row_index+1][column_index] for i in range(len(rows) - header_row_index - 1)]
		if feedback is not None:
			feedback.pushInfo("%s: %s" % (column_name, str(values)))
		return values

	def _collectProperties(self, parameters, context):
		props = {}

		props[self.BIOTOPE_RASTER] = self.parameterAsRasterLayer(parameters, self.BIOTOPE_RASTER, context)
		props[self.PARAMETER_TABLE_FILE] = self.parameterAsFile(parameters, self.PARAMETER_TABLE_FILE, context)
		props[self.OUTPUT_FOLDER] = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)

		return props

	def _addLayer(self, layer, group_name):
		self._layers.append((layer, group_name))
		"""
		self._processingContext.temporaryLayerStore().addMapLayer(layer)
		self._processingContext.addLayerToLoadOnCompletion(
			layer.id(),
			QgsProcessingContext.LayerDetails(
				name,
				self._processingContext.project(),
				'LAYER'
			)
		)
		"""	

	def name(self):
		return 'psteco_habitatnetwork'

	def displayName(self):
		return 'Habitat Network'

	def group(self):
		"""
		Returns the name of the group this algorithm belongs to. This string
		should be localised.
		"""
		return QgsProcessingAlgorithm.group(self)

	def groupId(self):
		"""
		Returns the unique ID of the group this algorithm belongs to. This
		string should be fixed for the algorithm, and must not be localised.
		The group id should be unique within each provider. Group id should
		contain lowercase alphanumeric characters only and no spaces or other
		formatting characters.
		"""
		return QgsProcessingAlgorithm.groupId(self)

	def createInstance(self):
		return HabitatNetworkAlgorithm()

	def tr(self, string):
		return QCoreApplication.translate('Processing', string)        