"""Opt-in table OCR UI acceptance; synthetic source and in-memory clipboard boundary."""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace


def run(directory,language,scale):
    from PySide6.QtCore import QCoreApplication,QEvent,QSettings,Qt
    from PySide6.QtGui import QColor,QImage,QPainter,QFont
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    from settings import get_tool_settings_manager
    config=get_tool_settings_manager(QSettings(str(directory/'settings.ini'),QSettings.Format.IniFormat))
    assert Path(config.qsettings.fileName()).resolve()==(directory/'settings.ini').resolve()
    from tests.native_image_editor import registry_digest
    registry_before=registry_digest()
    config.set_log_enabled(False);config.set_log_dir(str(directory/'logs'));config.set_clipboard_db_path(str(directory/'unused.db'))
    config.set_app_setting('language',language);config.set_app_setting('dialog_scale_percent',scale)
    from core.i18n import I18nManager
    from core.ui_scale import get_dialog_scale,get_ui_scale
    from core.ui_theme import get_ui_theme
    I18nManager.load_language(language);get_dialog_scale().init(config);get_ui_scale().init(config)
    theme=get_ui_theme().init(config,app)
    from text_recognition.result_window import show_text_recognition
    from text_recognition.table_window import TableRecognitionWindow
    import text_recognition.table_window as module
    from text_recognition import shutdown_recognition
    image=QImage(1050,360,QImage.Format.Format_ARGB32);image.fill(QColor('white'))
    painter=QPainter(image);font=QFont('Arial');font.setPixelSize(36);painter.setFont(font)
    cells=[['Name','Qty','Notes'],['Tea','2','Hot cup'],['Coffee','5','Cafe']]
    for r,row in enumerate(cells):
        for c,text in enumerate(row):
            painter.setPen(QColor('#172554'));painter.drawText(35+c*345,75+r*110,text)
    painter.end();source=directory/'source.png';assert image.save(str(source))
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    text_window=show_text_recognition(image);table=None;records=[]
    def wait(condition):
        end=time.monotonic()+45
        while time.monotonic()<end:
            app.processEvents()
            if condition():return
            time.sleep(.01)
        raise AssertionError('Native table UI timed out')
    original_app=module.QApplication;original_dialog=module.QFileDialog.getSaveFileName
    copied=[]
    try:
        wait(lambda:text_window._thread is None)
        assert text_window.table_button.isEnabled(),text_window.status_label.text()
        details=text_window._table_result
        (directory/'ocr-result.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
        QTest.mouseClick(text_window.table_button,Qt.MouseButton.LeftButton)
        table=next(w for w in app.topLevelWidgets() if isinstance(w,TableRecognitionWindow))
        assert table.cells()==cells,table.cells()
        assert table.image==image
        records.append({'check':'existing OCR entry -> real positioned OCR -> 3x3 reconstructed table without second OCR','passed':True})
        table.table.setCurrentCell(1,0)
        QTest.mouseClick(table.cell_editor.viewport(),Qt.MouseButton.LeftButton)
        table.cell_editor.selectAll();QTest.keyClicks(table.cell_editor,'Green tea')
        # Multiline/tab editing via the supported QTextEdit API; native key input above
        # separately verifies actual editor routing.
        table.cell_editor.setPlainText('Green tea\tpremium\nChecked')
        table.table.setCurrentCell(2,2);table.cell_editor.setPlainText('=1+2')
        table.table.setCurrentCell(1,0)
        assert not table.source._selection.rect().isEmpty()
        for color in ('light','dark'):
            theme.set_mode(color,persist=False);app.processEvents()
            assert table.grab().save(str(directory/f'table-{color}.png'))
        module.QApplication=SimpleNamespace(clipboard=lambda:SimpleNamespace(setText=copied.append))
        QTest.mouseClick(table.copy_button,Qt.MouseButton.LeftButton)
        assert len(copied)==1
        expected=[['Name','Qty','Notes'],['Green tea\tpremium\nChecked','2','Hot cup'],['Coffee','5',"'=1+2"]]
        assert list(csv.reader(io.StringIO(copied[0],newline=''),delimiter='\t'))==expected
        (directory/'edited.tsv').write_bytes(copied[0].encode('utf-8'))
        (directory/'expected.json').write_text(json.dumps(expected,ensure_ascii=False),encoding='utf-8')
        markdown=directory/'table.md'
        module.QFileDialog.getSaveFileName=lambda *a:(str(markdown),'Markdown (*.md)')
        QTest.mouseClick(table.save_button,Qt.MouseButton.LeftButton)
        saved=markdown.read_text('utf-8')
        assert '&#9;' in saved and '<br>Checked' in saved and '| --- | --- | --- |' in saved
        assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
        records.append({'check':'editable multiline/tab cells -> quoted TSV with formula protection and actual Markdown file; source unchanged','passed':True})
        # Structural corrections remain available after automatic reconstruction.
        QTest.mouseClick(table.row_add,Qt.MouseButton.LeftButton);assert table.table.rowCount()==4
        table.table.setCurrentCell(2,0);QTest.mouseClick(table.row_remove,Qt.MouseButton.LeftButton);assert table.table.rowCount()==3
        records.append({'check':'native insert/delete row buttons modify the editable table','passed':True})
    finally:
        module.QApplication=original_app;module.QFileDialog.getSaveFileName=original_dialog
        if table:table.close()
        text_window.close();shutdown_recognition(30000)
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        assert registry_digest()==registry_before
    result={'checks':records,'real_registry_unchanged':True,'os_clipboard_boundary':'captured in memory; independent Calc paste tested separately'}
    (directory/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',action='store_true');p.add_argument('--output',type=Path,required=True)
    p.add_argument('--language',default='zh');p.add_argument('--scale',type=int,default=100);a=p.parse_args()
    if not a.run:p.error('Requires --run')
    a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
    os.environ['QT_QPA_PLATFORM']='windows';os.environ['QT_ENABLE_HIGHDPI_SCALING']='0';os.environ['QT_SCALE_FACTOR']='1'
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness();run(a.output,a.language,a.scale)
