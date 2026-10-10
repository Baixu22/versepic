"""Geometry reconstruction, escaped exports and editable UI for simple OCR tables."""
import csv
import io
import random
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtGui import QColor,QImage

from text_recognition.table import MAX_BLOCKS,TableError,reconstruct_table,to_markdown,to_tsv,validate_cells
from text_recognition.table_window import TableRecognitionWindow


def block(text,x,y,w=80,h=20,score=.99):
    return {"text":text,"box":[[x,y],[x+w,y],[x+w,y+h],[x,y+h]],"score":score}


def fixture():
    return {"code":100,"data":[block(text,x,y) for y,row in [(10,["Name","Units","Cost"]),(50,["Green tea","2","12.50"]),(90,["Black tea","5","20.00"])] for x,text in zip((10,160,310),row,strict=True)]}


def source():
    image=QImage(450,160,QImage.Format.Format_ARGB32);image.fill(QColor('white'));return image


@pytest.fixture
def window(qapp):
    import shiboken6
    value=TableRecognitionWindow(source(),fixture())
    yield value
    if shiboken6.isValid(value):value.close()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_regular_table_shuffled_coordinates_preserves_multiword_cells():
    result=fixture();random.Random(914).shuffle(result['data'])
    table=reconstruct_table(result,450,160)
    assert table.cells==[['Name','Units','Cost'],['Green tea','2','12.50'],['Black tea','5','20.00']]
    assert table.boxes[1][0]==(10,50,90,70)
    assert not table.warnings and not table.uncertain


def test_missing_cell_does_not_shift_later_columns():
    result=fixture();result['data'].pop(4)
    table=reconstruct_table(result,450,160)
    assert table.cells[1]==['Green tea','','12.50'] and table.boxes[1][1] is None
    assert 'missing_cells' in table.warnings


def test_right_aligned_numbers_and_centered_short_headers_stay_in_column():
    result={'code':100,'data':[block('Product',10,0,90),block('Qty',200,0,30),block('Amount',330,0,70),
        block('Tea',10,50,40),block('1',215,50,15),block('1234.56',325,50,75)]}
    assert reconstruct_table(result,450,120).cells==[['Product','Qty','Amount'],['Tea','1','1234.56']]


def test_rows_tolerance_is_explicit_not_inferred_from_whitespace():
    result={'code':100,'data':[block('a b',10,10),block('c',160,18),block('d',10,70),block('e',160,70)]}
    assert len(reconstruct_table(result,300,120,row_tolerance=.5).cells)==2
    assert len(reconstruct_table(result,300,120,row_tolerance=.3).cells)==3


def test_spanning_box_is_flagged_not_treated_as_supported_merge():
    result=fixture();result['data'].append(block('Merged title',10,135,390,20))
    table=reconstruct_table(result,450,180)
    assert 'spanning' in table.warnings and any(r==3 for r,c in table.uncertain)


def test_low_score_and_rotated_boxes_are_marked_for_review():
    result=fixture();result['data'][4]['score']=.45;result['data'][5]['box'][1][1]+=8
    table=reconstruct_table(result,450,160)
    assert (1,1) in table.uncertain and 'rotated' in table.warnings and 'review_cells' in table.warnings


def test_one_ocr_line_remains_one_cell_without_fake_space_splitting():
    table=reconstruct_table({'code':100,'data':[block('Name  Qty  Cost',0,0,300)]},400,100)
    assert table.cells==[['Name  Qty  Cost']] and 'not_grid' in table.warnings


def test_invalid_boxes_are_skipped_with_warning_not_executed():
    result=fixture();result['data'] += [None,{'text':42},block('bad',float('nan'),0),block('outside',1000,0)]
    table=reconstruct_table(result,450,160)
    assert table.cells[0]==['Name','Units','Cost'] and 'invalid_boxes' in table.warnings


@pytest.mark.parametrize('result',[{},None,{'code':500}, {'code':100,'data':None}, {'code':100,'data':[]},
    {'code':100,'data':[block('x',0,0)]*(MAX_BLOCKS+1)}])
def test_invalid_empty_and_oversized_ocr_fails(result):
    with pytest.raises(TableError):reconstruct_table(result,450,160)


@pytest.mark.parametrize('rows,cols',[(201,1),(1,33),(200,21)])
def test_table_dimension_limits(rows,cols):
    with pytest.raises(TableError):validate_cells([['x']*cols for _ in range(rows)])


@pytest.mark.parametrize('cells',[[],[[]],[['a'],['a','b']],[[None]], [['x'*500001]]])
def test_invalid_export_matrix_is_rejected(cells):
    with pytest.raises(TableError):to_tsv(cells)
    with pytest.raises(TableError):to_markdown(cells)


def test_tsv_roundtrip_quotes_tabs_newlines_and_unicode():
    cells=[['商品 名','空 格','quote "ok"'],['line1\nline2','tab\tinside','a\r\nb'],['','','尾']]
    encoded=to_tsv(cells)
    assert list(csv.reader(io.StringIO(encoded,newline=''),delimiter='\t'))==cells
    assert encoded.endswith('\r\n')


@pytest.mark.parametrize('text',['=1+2','+SUM(A1)','-4','@value',' \t=HYPERLINK("x")'])
def test_formula_prefix_is_literal_by_default_but_can_be_explicitly_disabled(text):
    assert list(csv.reader(io.StringIO(to_tsv([[text]])),delimiter='\t'))==[["'"+text]]
    assert list(csv.reader(io.StringIO(to_tsv([[text]],protect_formulas=False)),delimiter='\t'))==[[text]]


def test_markdown_escapes_markup_pipes_tabs_and_multiline():
    cells=[['Key','Value'],['x|y','<script>\n![track](https://host/x)\t'+chr(96)+'code'+chr(96)]]
    text=to_markdown(cells)
    assert '| Key | Value |\n| --- | --- |' in text
    assert 'x\\|y' in text and '&lt;script&gt;<br>' in text and '&#9;' in text
    assert '\\!\\[track\\]' in text
    assert to_markdown([['data','v']],first_row_header=False).startswith('| Column 1 | Column 2 |')


def test_ui_cell_editor_handles_multiline_and_preserves_source(window):
    before=QImage(window.image)
    window.table.setCurrentCell(1,0);window.cell_editor.setPlainText('Changed\ttext\nline')
    assert window.cells()[1][0]=='Changed\ttext\nline' and window._dirty
    assert window.image==before
    assert window.source._selection.rect().getRect()==(10.,50.,80.,20.)


def test_ui_structure_changes_are_reflected_in_exports(window):
    window.table.setCurrentCell(0,0);window._structure('column',True)
    assert window.table.columnCount()==4 and window.cells()[0]==['Name','','Units','Cost']
    window._structure('row',True);assert window.table.rowCount()==4 and window.cells()[1]==['']*4
    window.table.setCurrentCell(1,1);window.cell_editor.setPlainText('manual')
    assert 'manual' in to_tsv(window.cells())
    window._structure('row',False);window.table.setCurrentCell(0,1);window._structure('column',False)
    assert window.cells()==reconstruct_table(fixture(),450,160).cells


def test_rebuild_confirmation_preserves_or_discards_edits_explicitly(window,monkeypatch):
    window.cell_editor.setPlainText('user edit')
    monkeypatch.setattr('text_recognition.table_window.show_confirm_dialog',lambda *a:False)
    window.rebuild();assert window.cells()[0][0]=='user edit'
    monkeypatch.setattr('text_recognition.table_window.show_confirm_dialog',lambda *a:True)
    window.rebuild();assert window.cells()[0][0]=='Name' and not window._dirty


def test_tsv_copy_uses_current_cells_and_does_not_save_file(window,monkeypatch):
    import text_recognition.table_window as module
    copy=Mock();monkeypatch.setattr(module,'QApplication',Mock(clipboard=Mock(return_value=Mock(setText=copy))))
    window.cell_editor.setPlainText('=2+3');window.copy_tsv()
    assert copy.call_count==1 and copy.call_args.args[0].startswith("'=2+3\t")


def test_markdown_save_is_atomic_and_uses_edited_grid(window,monkeypatch,tmp_path):
    target=tmp_path/'table.md'
    monkeypatch.setattr('text_recognition.table_window.QFileDialog.getSaveFileName',lambda *a:(str(target),'Markdown'))
    window.cell_editor.setPlainText('edited');window.save_markdown()
    assert target.read_text('utf-8')==to_markdown(window.cells())
    assert list(tmp_path.iterdir())==[target]


def test_window_close_releases_image_and_qt_widgets(window,qapp):
    import shiboken6
    window.close();assert window.image.isNull() and window.ocr_result is None
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(window)


def test_existing_ocr_result_entry_reuses_details_no_second_recognition(qapp,monkeypatch):
    from text_recognition.result_window import TextRecognitionWindow
    start=Mock();monkeypatch.setattr('text_recognition.result_window.recognize_async',start)
    opened=Mock();monkeypatch.setattr('text_recognition.table_window.show_table_recognition',opened)
    window=TextRecognitionWindow(source(),initial_result=fixture())
    assert window.table_button.isEnabled()
    window._open_table();assert opened.call_args.args[1]==fixture()
    start.assert_not_called();window.close()


def test_late_ocr_details_after_close_cannot_reopen_table(qapp,monkeypatch):
    from text_recognition.result_window import TextRecognitionWindow
    window=TextRecognitionWindow(source(),initial_result=fixture())
    window.close();window._on_table_details(fixture(),'')
    assert window._table_result is None and window._table_image is None


def test_colliding_text_boxes_are_joined_and_flagged_not_discarded():
    data=[block('A',0,0,60),block('B',200,0,60),block('C',400,0,60),
          block('part 1',0,50,30),block('part 2',40,50,30)]
    table=reconstruct_table({'code':100,'data':data},500,100)
    assert table.cells[1][0]=='part 1\npart 2' and 'collision' in table.warnings and (1,0) in table.uncertain


def test_single_cell_minimum_and_structure_limits(window):
    window.table.setRowCount(1);window.table.setColumnCount(1);window.table.setCurrentCell(0,0)
    window._structure('row',False);window._structure('column',False)
    assert window.table.rowCount()==1 and window.table.columnCount()==1
    window.table.setColumnCount(32);window._structure('column',True)
    assert window.table.columnCount()==32


def test_invalid_regrouping_does_not_silently_export_old_matrix(window,monkeypatch):
    window.ocr_result={'code':100,'data':[]};window.rebuild()
    assert not window.copy_button.isEnabled() and not window.save_button.isEnabled()


def test_low_confidence_table_cells_get_visible_annotation(qapp):
    from PySide6.QtCore import Qt
    result=fixture();result['data'][4]['score']=.3
    window=TableRecognitionWindow(source(),result)
    item=window.table.item(1,1)
    assert 'Low confidence' in item.toolTip()
    assert item.background().color()==QColor('#fff0ba')
    assert item.data(Qt.ItemDataRole.UserRole)==(160,50,240,70)
    assert 'Uncertain cells' in window.warning.text()
    window.close()


@pytest.mark.parametrize('language',['en','zh','ja','ko'])
def test_table_translations_cover_every_ui_literal(language):
    import ast
    from pathlib import Path
    from PySide6.QtCore import QTranslator
    main=Path(__file__).resolve().parents[1];translator=QTranslator()
    assert translator.load(str(main/'translations'/f'app_{language}.qm'))
    tree=ast.parse((main/'text_recognition'/'table_window.py').read_text('utf-8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='tr' and node.args and isinstance(node.args[0],ast.Constant):
            assert translator.translate('TableRecognitionWindow',node.args[0].value),(language,node.args[0].value)
    assert translator.translate('TextRecognitionWindow','Review table…')


def test_unicode_formula_with_whitespace_gets_prefix():
    value='\u3000=1+1'
    assert next(csv.reader(io.StringIO(to_tsv([[value]])),delimiter='\t'))==["'"+value]


def test_markdown_save_cancel_does_not_touch_any_file(window,monkeypatch,tmp_path):
    monkeypatch.setattr('text_recognition.table_window.QFileDialog.getSaveFileName',lambda *a:('',''))
    window.save_markdown();assert list(tmp_path.iterdir())==[]


def test_ordinary_ocr_text_edit_does_not_relabel_original_geometry(qapp,monkeypatch):
    from text_recognition.result_window import TextRecognitionWindow
    open_table=Mock();monkeypatch.setattr('text_recognition.table_window.show_table_recognition',open_table)
    window=TextRecognitionWindow(source(),initial_result=fixture());window.text_edit.setPlainText('user changed plain text')
    window._open_table()
    assert open_table.call_args.args[1]==fixture()
    window.close()


def test_table_keeps_its_own_image_after_ocr_window_closes(qapp):
    from text_recognition.result_window import TextRecognitionWindow
    text=TextRecognitionWindow(source(),initial_result=fixture())
    table=TableRecognitionWindow(text._table_image,text._table_result)
    text.close()
    assert not table.image.isNull() and table.cells()[1][0]=='Green tea'
    table.close()


def test_markdown_write_failure_keeps_existing_file(window,monkeypatch,tmp_path):
    target=tmp_path/'existing.md';target.write_text('original')
    monkeypatch.setattr('text_recognition.table_window.QFileDialog.getSaveFileName',lambda *a:(str(target),'Markdown'))
    fake=Mock();fake.open.return_value=True;fake.write.return_value=-1
    monkeypatch.setattr('text_recognition.table_window.QSaveFile',lambda *a:fake)
    window.save_markdown();fake.cancelWriting.assert_called_once();fake.commit.assert_not_called()
    assert target.read_text()=='original'


def test_coordinate_outliers_and_long_text_limits():
    bad=fixture();bad['data'].append(block('X'*500001,0,0))
    with pytest.raises(TableError):reconstruct_table(bad,450,160)
    grid={'code':100,'data':[block(str(i),i*10,0,5,10) for i in range(33)]}
    with pytest.raises(TableError):reconstruct_table(grid,500,100)
    rows={'code':100,'data':[block(str(i),0,i*30,5,10) for i in range(201)]}
    with pytest.raises(TableError):reconstruct_table(rows,50,10000)
