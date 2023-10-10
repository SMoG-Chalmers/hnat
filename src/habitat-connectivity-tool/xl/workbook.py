"""
Habitat Connectivity Tool
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

import xml.etree.ElementTree as ET
import zipfile

def OpenWorkbook(path):
	return Workbook(path)

def ValueFromString(s):
		try:
			return int(s)
		except:
			pass
		try:
			return float(s)
		except:
			pass
		return s

class SheetDef:
	def __init__(self, name, rid):
		self.name = name
		self.rid = rid

class Workbook:
	def __init__(self, path):
		self._archive = zipfile.ZipFile(path, 'r')
		self._rels = self._loadRels()
		self._sheetDefs = self._loadSheetDefs()
		self._sharedStrings = self._loadSharedStrings()

	def loadSheetData(self, index):
		ns = {
			'': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
		}
		row_tag = '{%s}row' % ns['']
		c_tag = '{%s}c' % ns['']
		v_tag = '{%s}v' % ns['']
		doc = self._loadXml(self._sheetPath(index))
		root = doc.getroot()
		raw_rows = []
		sheetData_node = root.find('{%s}sheetData' % ns[''])
		for row_node in sheetData_node.findall(row_tag):
			spans = row_node.attrib['spans']
			length = int(spans[spans.find(':') + 1:])
			row = [None] * length
			for c_node in row_node.findall(c_tag):
				ref = c_node.attrib['r']
				col = ord(ref[0]) - ord('A')
				t = c_node.attrib.get('t')
				v_node = c_node.find(v_tag)
				if v_node is not None:
					if t == 's':
						row[col] = self._sharedStrings[int(v_node.text)]
					else:
						row[col] = ValueFromString(v_node.text)
			raw_rows.append((int(row_node.get('r')), row))
		row_count = max([r[0] for r in raw_rows])
		rows = [[]] * row_count
		for r in raw_rows:
			rows[r[0] - 1] = r[1]
		return rows

	def sheetCount(self):
		return len(self._sheetDefs)

	def sheetName(self, index):
		return self._sheetDefs[index].name

	def _loadRels(self):
		root = self._loadXml('xl/_rels/workbook.xml.rels').getroot()
		rels = {}
		for child in root:
			if 'Relationship' == self._stripNameSpace(child.tag):
				rels[child.get('Id')] = child.get('Target')
		return rels

	def _loadSheetDefs(self):
		ns = {
			'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
		}
		doc = self._loadXml('xl/workbook.xml')
		root = doc.getroot()
		sheet_defs = []
		for child in root:
			if 'sheets' == self._stripNameSpace(child.tag):
				for child2 in child:
					if 'sheet' == self._stripNameSpace(child2.tag):
						name = child2.get('name')
						rid = child2.get('{%s}id' % ns['r'])
						sheet_defs.append(SheetDef(name, rid))
		return sheet_defs

	def _loadSharedStrings(self):
		ns = {
			'': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
		}
		doc = self._loadXml('xl/sharedStrings.xml')
		root = doc.getroot()
		shared_strings = []
		for si in root.findall('{%s}si' % ns['']):
			t = si.find('{%s}t' % ns[''])
			if t is not None:
				shared_strings.append(t.text)
		return shared_strings

	def _sheetPath(self, index):
		return 'xl/'+self._rels[self._sheetDefs[index].rid]

	def _loadXml(self, path):
		f = self._archive.open(path)
		return ET.parse(f)

	def _stripNameSpace(self, tag):
		i = tag.rfind('}')
		return tag if i < 0 else tag[i+1:]