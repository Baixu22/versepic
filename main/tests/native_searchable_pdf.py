"""Native PDF collection/export acceptance with synthetic pixels and isolated settings."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def run(directory,language,scale):
    from PySide6.QtCore import QCoreApplication,QEvent,QPoint,QRect,QSettings,QSize,QTimer,Qt
    from PySide6.QtGui import QColor,QFont,QImage,QPainter
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PySide6.QtPdf import QPdfDocument
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    from settings import get_tool_settings_manager
    config=get_tool_settings_manager(QSettings(str(directory/'settings.ini'),QSettings.Format.IniFormat))
    assert Path(config.qsettings.fileName()).resolve()==(directory/'settings.ini').resolve()
    from tests.native_image_editor import registry_digest
    registry_before=registry_digest()
    config.set_log_enabled(False);config.set_log_dir(str(directory/'logs'));config.set_clipboard_db_path(str(directory/'unused-history.db'))
    config.set_app_setting('language',language);config.set_app_setting('dialog_scale_percent',scale)
    from core.i18n import I18nManager
    from core.ui_scale import get_dialog_scale,get_ui_scale
    from core.ui_theme import get_ui_theme
    I18nManager.load_language(language);get_dialog_scale().init(config);get_ui_scale().init(config)
    theme=get_ui_theme().init(config,app)
    from core.save import SaveService
    from core.image_layout import PageOptions
    from core.searchable_pdf import PdfTextReport
    from text_recognition.redaction import redact_image
    from ui.image_layout_dialog import ImageLayoutDialog
    from text_recognition import shutdown_recognition
    page=QImage(1000,600,QImage.Format.Format_ARGB32);page.fill(QColor('#f1f5fb'))
    p=QPainter(page);font=QFont('Microsoft YaHei');font.setPixelSize(48);p.setFont(font);p.setPen(QColor('#172554'))
    for y,text in [(100,'SEARCHABLE ALPHA 2048'),(220,'搜索测试 1234'),(340,'日本語 テスト'),(460,'한국어 테스트')]:p.drawText(40,y,text)
    p.end();page.setText('OldOCR','STALE_PRIVATE_TEXT')
    private=QImage(1000,600,QImage.Format.Format_ARGB32);private.fill(QColor('white'))
    p=QPainter(private);p.setFont(font);p.setPen(QColor('black'));p.drawText(40,100,'PUBLIC VISIBLE 2468');p.drawText(40,240,'PRIVATE SECRET 918273');p.end()
    redacted=redact_image(private,[QRect(0,170,1000,150)])
    blank=QImage(1000,600,QImage.Format.Format_ARGB32);blank.fill(QColor('white'))
    source_hashes=[]
    for name,image in [('multilingual',page),('redacted',redacted),('blank',blank)]:
        path=directory/(name+'.png');assert image.save(str(path));source_hashes.append((path,hashlib.sha256(path.read_bytes()).hexdigest()))
    window=ImageLayoutDialog(config);records=[]
    def wait(condition,seconds=90):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            app.processEvents()
            if condition():return
            time.sleep(.01)
        raise AssertionError('Native searchable PDF condition timed out')
    def extract(path):
        doc=QPdfDocument();assert doc.load(str(path))==QPdfDocument.Error.None_
        pages=[]
        for i in range(doc.pageCount()):
            text=doc.getAllText(i).text();render=doc.render(i,QSize(800,1132));assert not render.isNull()
            assert render.save(str(directory/(path.stem+f'-page-{i+1}.png')))
            pages.append({'text':text,'size':[doc.pagePointSize(i).width(),doc.pagePointSize(i).height()]})
        doc.close();return pages
    try:
        window.add_image('Multilingual source',page);window.add_image('Already redacted pixels',redacted);window.add_image('Blank page',blank)
        window.mode.setCurrentIndex(window.mode.findData('pdf'));window.paper.setCurrentIndex(window.paper.findData('a4'))
        window.update_preview();assert not window.searchable.isChecked()
        window.show();app.processEvents()
        QTest.mouseClick(window.searchable,Qt.MouseButton.LeftButton,pos=QPoint(10,window.searchable.height()//2))
        assert window.searchable.isChecked()
        window.list.setCurrentRow(0);window.update_preview()
        for color in ('light','dark'):
            theme.set_mode(color,persist=False);app.processEvents();assert window.grab().save(str(directory/f'options-{color}.png'))
        target=directory/'searchable.pdf';assert window.start_export(str(target));wait(lambda:window._worker is None)
        report=window._last_text_report;assert report is not None
        pages=extract(target)
        assert len(pages)==3 and 'SEARCHABLE ALPHA 2048' in pages[0]['text'] and '搜索' in pages[0]['text'],pages
        assert 'PUBLIC VISIBLE 2468' in pages[1]['text'] and 'PRIVATE' not in pages[1]['text'] and '918273' not in pages[1]['text']
        assert pages[2]['text']=='' and report.pages[2]['image_only']
        assert all('STALE_PRIVATE_TEXT' not in p['text'] for p in pages)
        (directory/'text-report.json').write_text(json.dumps(report.pages,indent=2),encoding='utf-8')
        (directory/'extracted-pages.json').write_text(json.dumps(pages,ensure_ascii=False,indent=2),encoding='utf-8')
        QTimer.singleShot(200,lambda: QApplication.activeModalWidget().accept() if QApplication.activeModalWidget() else None)
        window.show_pdf_report()
        records.append({'check':'real background OCR and multipage searchable A4 output; redacted secrets and stale metadata not embedded; blank page reported','passed':True})
        # Same pixels in image-only PDF must render exactly the same, without text.
        plain=directory/'image-only.pdf';service=SaveService(config)
        assert service.save_image_pages(window.images(),str(plain),window.page_options())
        plain_pages=extract(plain);assert all(not p['text'] for p in plain_pages)
        for i in range(3):
            assert QImage(str(directory/f'searchable-page-{i+1}.png'))==QImage(str(directory/f'image-only-page-{i+1}.png'))
        records.append({'check':'image-only and searchable PDFs have identical rendered page pixels; only selectable text differs','passed':True})
        # Rotate an inverted input before fresh OCR; geometry and source remain coherent.
        from PySide6.QtGui import QTransform
        rotated_input=page.transformed(QTransform().rotate(180));rotation=PdfTextReport()
        rotated=directory/'rotated.pdf'
        assert service.save_image_pages([rotated_input],str(rotated),PageOptions('letter',True,10,180),searchable=True,text_report=rotation)
        rotated_pages=extract(rotated);assert 'SEARCHABLE ALPHA 2048' in rotated_pages[0]['text']
        records.append({'check':'180-degree input rotation is applied before OCR and landscape Letter pagination','passed':True})
        # Real close/cancel on a busy UI leaves the existing destination untouched.
        existing=directory/'cancel.pdf';existing.write_bytes(b'ORIGINAL')
        assert window.start_export(str(existing));QTest.mouseClick(window.cancel_export,Qt.MouseButton.LeftButton)
        wait(lambda:window._worker is None);assert existing.read_bytes()==b'ORIGINAL'
        assert not list(directory.glob('.versepic-*'))
        for path,digest in source_hashes:assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
        records.append({'check':'visible cancel preserves old file and removes staging; all source image hashes unchanged','passed':True})
    finally:
        window.shutdown();window.close();shutdown_recognition(30000)
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        assert registry_digest()==registry_before
    (directory/'result.json').write_text(json.dumps(records,indent=2),encoding='utf-8');print(json.dumps(records,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--language',default='zh');parser.add_argument('--scale',type=int,default=100);args=parser.parse_args()
    if not args.run:parser.error('Requires --run')
    args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=True)
    os.environ['QT_QPA_PLATFORM']='windows';os.environ['QT_ENABLE_HIGHDPI_SCALING']='0';os.environ['QT_SCALE_FACTOR']='1'
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness();run(args.output,args.language,args.scale)
