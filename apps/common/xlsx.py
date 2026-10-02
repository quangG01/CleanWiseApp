"""Small dependency-free XLSX writer for tabular report exports (no formulas)."""
import re
from decimal import Decimal
from io import BytesIO
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZIP_DEFLATED, ZipFile

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def _xml(root):
    return tostring(root, encoding='utf-8', xml_declaration=True)


def workbook_bytes(sheets):
    output = BytesIO()
    workbook = Element('workbook', xmlns=NS, attrib={'xmlns:r': REL})
    sheet_list = SubElement(workbook, 'sheets')
    relationships = Element('Relationships', xmlns='http://schemas.openxmlformats.org/package/2006/relationships')
    content = Element('Types', xmlns='http://schemas.openxmlformats.org/package/2006/content-types')
    SubElement(content, 'Default', Extension='rels', ContentType='application/vnd.openxmlformats-package.relationships+xml')
    SubElement(content, 'Default', Extension='xml', ContentType='application/xml')
    SubElement(content, 'Override', PartName='/xl/workbook.xml', ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml')
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for index, (name, rows) in enumerate(sheets, 1):
            SubElement(sheet_list, 'sheet', name=name, sheetId=str(index), attrib={'r:id': f'rId{index}'})
            SubElement(relationships, 'Relationship', Id=f'rId{index}', Type=f'{REL}/worksheet', Target=f'worksheets/sheet{index}.xml')
            SubElement(content, 'Override', PartName=f'/xl/worksheets/sheet{index}.xml', ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml')
            sheet = Element('worksheet', xmlns=NS)
            views = SubElement(sheet, 'sheetViews')
            view = SubElement(views, 'sheetView', workbookViewId='0')
            SubElement(view, 'pane', ySplit='1', topLeftCell='A2', activePane='bottomLeft', state='frozen')
            cols = SubElement(sheet, 'cols')
            SubElement(cols, 'col', min='1', max='30', width='24', customWidth='1')
            data = SubElement(sheet, 'sheetData')
            for row_index, row in enumerate(rows, 1):
                node = SubElement(data, 'row', r=str(row_index))
                for col_index, value in enumerate(row, 1):
                    letter, number = '', col_index
                    while number:
                        number, remainder = divmod(number - 1, 26)
                        letter = chr(65 + remainder) + letter
                    cell = SubElement(node, 'c', r=f'{letter}{row_index}')
                    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
                        SubElement(cell, 'v').text = str(value)
                    else:
                        cell.set('t', 'inlineStr')
                        text = SubElement(SubElement(cell, 'is'), 't', attrib={'xml:space': 'preserve'})
                        text.text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value if value is not None else ''))
            archive.writestr(f'xl/worksheets/sheet{index}.xml', _xml(sheet))
        archive.writestr('xl/workbook.xml', _xml(workbook))
        archive.writestr('xl/_rels/workbook.xml.rels', _xml(relationships))
        archive.writestr('[Content_Types].xml', _xml(content))
        package_rels = Element('Relationships', xmlns='http://schemas.openxmlformats.org/package/2006/relationships')
        SubElement(package_rels, 'Relationship', Id='rId1', Type=f'{REL}/officeDocument', Target='xl/workbook.xml')
        archive.writestr('_rels/.rels', _xml(package_rels))
    return output.getvalue()
