"""Real Qt PDF extraction/rendering, page geometry and fresh-pixel OCR safety."""
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QRect,QSize
from PySide6.QtGui import QColor,QFontDatabase,QImage
from PySide6.QtPdf import QPdfDocument

from core.image_layout import PageOptions,ImageLayoutError,render_pdf_preview
from core.save import SaveService
from core.searchable_pdf import PdfTextReport,positioned_lines,text_layout
from settings.tool_settings import ToolSettingsManager


@pytest.fixture(scope='module',autouse=True)
def fonts(qapp):
    # Offscreen Qt has no system font inventory; load real installed fonts for
    # PDF text tests rather than passing outlined dummy glyphs as searchable.
    ids=[]
    for name in ('arial.ttf','msyh.ttc','malgun.ttf','meiryo.ttc'):
        file=Path('C:/Windows/Fonts')/name
        if file.exists():
            identifier=QFontDatabase.addApplicationFont(str(file))
            if identifier>=0:ids.append(identifier)
    assert ids and text_layout('Search 搜索 テスト 한국어') is not None
    yield
    for identifier in ids:QFontDatabase.removeApplicationFont(identifier)


@pytest.fixture
def service(tmp_settings):return SaveService(ToolSettingsManager(tmp_settings))


def image(width=400,height=200,color='#ddeeff'):
    value=QImage(width,height,QImage.Format.Format_ARGB32);value.fill(QColor(color));return value


def block(text='Searchable 123',x=30,y=30,w=250,h=35,score=.99):
    return {'text':text,'box':[[x,y],[x+w,y],[x+w,y+h],[x,y+h]],'score':score}


def result(*blocks):return {'code':100,'data':list(blocks) or [block()]}


def read_pdf(filename,size=QSize(800,400)):
    doc=QPdfDocument();assert doc.load(str(filename))==QPdfDocument.Error.None_
    pages=[(doc.getAllText(i).text(),doc.render(i,size),doc.pagePointSize(i)) for i in range(doc.pageCount())]
    doc.close();return pages


def mock_ocr(monkeypatch,data):
    monkeypatch.setattr('ocr.is_ocr_available',lambda:True)
    recognize=Mock(return_value=data);monkeypatch.setattr('ocr.recognize_text',recognize);return recognize


def test_searchable_text_is_extracted_but_render_is_identical_to_image_only(service,tmp_path,monkeypatch):
    source=image();mock_ocr(monkeypatch,result());options=PageOptions(margin_mm=0)
    report=PdfTextReport();search=tmp_path/'search.pdf';plain=tmp_path/'image.pdf'
    assert service.save_image_pages([source],str(search),options,searchable=True,text_report=report)
    assert service.save_image_pages([source],str(plain),options)
    a,b=read_pdf(search)[0],read_pdf(plain)[0]
    assert 'Searchable 123' in a[0] and b[0]=='' and a[1]==b[1]
    assert report.lines==1 and not report.pages[0]['image_only']


def test_transparent_source_does_not_expose_hidden_glyphs(service,tmp_path,monkeypatch):
    source=image(color='transparent');mock_ocr(monkeypatch,result(block('NOT VISIBLE')))
    report=PdfTextReport();target=tmp_path/'transparent.pdf'
    assert service.save_image_pages([source],str(target),PageOptions(margin_mm=0),searchable=True,text_report=report)
    text,render,_=read_pdf(target)[0]
    assert 'NOT VISIBLE' in text and render.pixelColor(150,80)==QColor('white')


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_rotation_changes_actual_ocr_pixels_and_pdf_page_size(service,tmp_path,monkeypatch,rotation):
    source=image(400,200);source.setPixelColor(0,0,QColor('red'))
    seen=[]
    def recognize(page,**kwargs):
        seen.append(QImage(page));return result(block('Rotated',5,5,80,15))
    monkeypatch.setattr('ocr.recognize_text',recognize);monkeypatch.setattr('ocr.is_ocr_available',lambda:True)
    target=tmp_path/f'{rotation}.pdf';report=PdfTextReport();options=PageOptions(margin_mm=0,rotation=rotation)
    assert service.save_image_pages([source],str(target),options,searchable=True,text_report=report)
    expected=(200,400) if rotation in (90,270) else (400,200)
    assert (seen[0].width(),seen[0].height())==expected
    assert seen[0].devicePixelRatio()==1 and not seen[0].hasAlphaChannel()
    text,_,page=read_pdf(target)[0];assert 'Rotated' in text
    assert (round(page.width()),round(page.height()))==tuple(int(v*.75) for v in expected)
    assert report.pages[0]['pixel_size']==list(expected)
    assert source.pixelColor(0,0)==QColor('red')


@pytest.mark.parametrize('options',[PageOptions('a4',False,10),PageOptions('a4',True,15),PageOptions('letter',False,5)])
def test_multilingual_scaled_pages_and_reading_order(service,tmp_path,monkeypatch,options):
    blocks=[block('Bottom',20,120,120,20),block('Right',220,20,100,20),block('Left',20,20,100,20),block('搜索 テスト 한국어',20,70,300,30)]
    mock_ocr(monkeypatch,result(*blocks));target=tmp_path/'multi.pdf';report=PdfTextReport()
    assert service.save_image_pages([image(),image(600,300)],str(target),options,searchable=True,text_report=report)
    pages=read_pdf(target)
    assert len(pages)==2 and report.lines==8
    for text,_,page in pages:
        assert all(word in text for word in ('Left','Right','Bottom','搜索','テスト','한국어'))
        assert text.index('Left')<text.index('Right')<text.index('Bottom')
        expected=options.geometry(image())[0];assert page==expected


def test_text_selection_geometry_aligns_with_ocr_box(service,tmp_path,monkeypatch):
    mock_ocr(monkeypatch,result(block('Alignment',40,50,240,40)))
    target=tmp_path/'align.pdf';assert service.save_image_pages([image()],str(target),PageOptions(margin_mm=0),searchable=True)
    doc=QPdfDocument();assert doc.load(str(target))==QPdfDocument.Error.None_
    selection=doc.getSelectionAtIndex(0,0,len('Alignment'))
    rect=selection.boundingRectangle()
    assert abs(rect.x()-30)<4 and abs(rect.y()-37.5)<6
    assert abs(rect.width()-180)<8 and 10<rect.height()<35
    doc.close()


@pytest.mark.parametrize('ocr', [None,{'code':500,'data':[]},{'code':100,'data':[]},{'code':100,'data':'bad'}])
def test_failed_blank_or_invalid_ocr_yields_reported_image_only_page(service,tmp_path,monkeypatch,ocr):
    mock_ocr(monkeypatch,ocr);report=PdfTextReport();target=tmp_path/'fallback.pdf'
    assert service.save_image_pages([image()],str(target),PageOptions(),searchable=True,text_report=report)
    assert report.lines==0 and report.pages[0]['image_only'] and read_pdf(target)[0][0]==''
    if ocr!={'code':100,'data':[]}:assert report.pages[0]['warnings']


def test_unavailable_ocr_not_called_and_image_only_mode_never_calls_ocr(service,tmp_path,monkeypatch):
    recognize=mock_ocr(monkeypatch,result());monkeypatch.setattr('ocr.is_ocr_available',lambda:False)
    report=PdfTextReport()
    assert service.save_image_pages([image()],str(tmp_path/'no-engine.pdf'),PageOptions(),searchable=True,text_report=report)
    assert report.pages[0]['warnings']=={'ocr_failed':1}
    assert service.save_image_pages([image()],str(tmp_path/'plain.pdf'),PageOptions())
    recognize.assert_not_called()


def test_missing_font_is_reported_and_does_not_draw_square_placeholders(service,tmp_path,monkeypatch):
    mock_ocr(monkeypatch,result());monkeypatch.setattr('core.searchable_pdf.QFontDatabase.families',lambda:[])
    report=PdfTextReport();target=tmp_path/'no-font.pdf'
    assert service.save_image_pages([image()],str(target),PageOptions(),searchable=True,text_report=report)
    assert report.pages[0]['warnings']['missing_glyphs']==1 and read_pdf(target)[0][0]==''


def test_unsupported_codepoint_skips_whole_line(service,tmp_path,monkeypatch):
    mock_ocr(monkeypatch,result(block('Valid '+chr(0x10fffd)+' invalid')));report=PdfTextReport();target=tmp_path/'glyph.pdf'
    assert service.save_image_pages([image()],str(target),PageOptions(),searchable=True,text_report=report)
    assert report.lines==0 and report.pages[0]['warnings']['missing_glyphs']==1


def test_invalid_and_perspective_boxes_are_not_hidden_at_wrong_positions():
    source=image()
    bad=[block(x=-5),block(x=float('nan')),{'text':'SECRET','box':[[10,10],[200,10],[130,90],[10,40]]}]
    lines,warnings=positioned_lines(result(*bad),source)
    assert not lines and warnings['invalid_box']==3


def test_rotated_rectangle_keeps_unicode_text_and_coordinates(service,tmp_path,monkeypatch):
    b={'text':'Turn 90','box':[[150,20],[150,170],[120,170],[120,20]],'score':.9}
    mock_ocr(monkeypatch,result(b));target=tmp_path/'rotated-line.pdf'
    assert service.save_image_pages([image()],str(target),PageOptions(margin_mm=0),searchable=True)
    assert 'Turn 90' in read_pdf(target)[0][0]


def test_redacted_export_only_ocr_actual_flat_pixels_never_uses_cached_strings(service,tmp_path,monkeypatch):
    from text_recognition.redaction import redact_image
    source=image();source.setText('OCR','RAW_PRIVATE_TEXT')
    redacted=redact_image(source,[QRect(0,0,400,100)])
    def recognize(actual,**kwargs):
        assert actual.pixelColor(50,50)==QColor('black') and not actual.textKeys()
        return result(block('VISIBLE ONLY',10,125,250,25))
    monkeypatch.setattr('ocr.recognize_text',recognize);monkeypatch.setattr('ocr.is_ocr_available',lambda:True)
    target=tmp_path/'redacted.pdf';assert service.save_image_pages([redacted],str(target),PageOptions(),searchable=True)
    text=read_pdf(target)[0][0];assert 'VISIBLE ONLY' in text and 'PRIVATE' not in text


def test_cancel_during_ocr_preserves_existing_pdf_and_removes_staging(service,tmp_path,monkeypatch):
    cancel=threading.Event();target=tmp_path/'keep.pdf';target.write_bytes(b'ORIGINAL')
    def recognize(*args,**kwargs):cancel.set();return result(block('LATE PRIVATE'))
    monkeypatch.setattr('ocr.recognize_text',recognize);monkeypatch.setattr('ocr.is_ocr_available',lambda:True)
    assert not service.save_image_pages([image()],str(target),PageOptions(),searchable=True,cancelled=cancel.is_set)
    assert target.read_bytes()==b'ORIGINAL' and not list(tmp_path.glob('.versepic-*'))


def test_cancel_after_first_page_keeps_original(service,tmp_path,monkeypatch):
    mock_ocr(monkeypatch,result());cancel=threading.Event();target=tmp_path/'keep.pdf';target.write_bytes(b'ORIGINAL')
    assert not service.save_image_pages([image(),image()],str(target),PageOptions(),searchable=True,
        cancelled=cancel.is_set,progress=lambda *a:cancel.set())
    assert target.read_bytes()==b'ORIGINAL' and not list(tmp_path.glob('.versepic-*'))


def test_ocr_failure_payload_is_not_exposed_in_report_or_logs(service,tmp_path,monkeypatch):
    from core.capture_privacy import sensitive_ocr
    def recognize(*args,**kwargs):
        assert sensitive_ocr.get();raise ValueError('SECRET_EXCEPTION')
    monkeypatch.setattr('ocr.recognize_text',recognize);monkeypatch.setattr('ocr.is_ocr_available',lambda:True)
    report=PdfTextReport();assert service.save_image_pages([image()],str(tmp_path/'error.pdf'),PageOptions(),searchable=True,text_report=report)
    assert 'SECRET' not in str(report.pages) and not sensitive_ocr.get()


def test_page_rotation_preview_matches_image_only_output(service,tmp_path):
    for rotation in (0,90,180,270):
        source=image(40,20);source.setPixelColor(0,0,QColor('red'));options=PageOptions(margin_mm=0,rotation=rotation)
        preview=render_pdf_preview(source,options)
        size=options.geometry(source)[0]
        assert (preview.width(),preview.height())==(int(size.width()),int(size.height()))
        target=tmp_path/f'plain-{rotation}.pdf';assert service.save_image_pages([source],str(target),options)
        assert read_pdf(target)[0][2]==size
    with pytest.raises(ImageLayoutError):PageOptions(rotation=45).geometry(source)


def test_collection_ui_snapshots_searchable_option_and_reports_result(qapp,qtbot,tmp_path,service,monkeypatch):
    from ui.image_layout_dialog import ImageLayoutDialog
    import shiboken6
    mock_ocr(monkeypatch,result());dialog=ImageLayoutDialog(service.config_manager)
    try:
        dialog.add_image('source',image());dialog.mode.setCurrentIndex(dialog.mode.findData('pdf'))
        dialog.update_preview();assert dialog.searchable.isEnabled() and not dialog.searchable.isChecked()
        dialog.searchable.setChecked(True);target=tmp_path/'ui.pdf'
        assert dialog.start_export(str(target));qtbot.waitUntil(lambda:dialog._worker is None,timeout=15000)
        assert dialog._last_text_report.lines==1 and not dialog.pdf_report_button.isHidden()
        assert '1 of 1' in dialog.status.text() and 'Searchable' in read_pdf(target)[0][0]
    finally:
        if shiboken6.isValid(dialog):dialog.close()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_plain_pdf_remains_default_and_does_not_import_history_ocr(qapp,monkeypatch):
    from text_recognition.result_window import TextRecognitionWindow
    from ui.image_layout_dialog import ImageLayoutDialog
    source=image();window=TextRecognitionWindow(source,initial_result=result(block('STALE PRIVATE')))
    window._open_pdf_output()
    dialog=next(w for w in qapp.topLevelWidgets() if isinstance(w,ImageLayoutDialog))
    try:
        assert dialog.images()==[source] and not dialog.searchable.isChecked()
        assert not hasattr(dialog,'_table_result')
    finally:dialog.close();window.close()


def test_cancel_in_text_layer_restores_painter_state_and_keeps_target(service,tmp_path,monkeypatch):
    import core.searchable_pdf as module
    mock_ocr(monkeypatch,result(block('One'),block('Two',30,90)))
    original=module.text_layout;cancel=threading.Event()
    def shaped(text):
        output=original(text);cancel.set();return output
    monkeypatch.setattr(module,'text_layout',shaped)
    target=tmp_path/'old.pdf';target.write_bytes(b'OLD')
    assert not service.save_image_pages([image()],str(target),PageOptions(),searchable=True,cancelled=cancel.is_set)
    assert target.read_bytes()==b'OLD' and not list(tmp_path.glob('.versepic-*'))


def test_pdf_replace_error_preserves_original_and_removes_staging(service,tmp_path,monkeypatch):
    mock_ocr(monkeypatch,result());target=tmp_path/'existing.pdf';target.write_bytes(b'OLD')
    def fail(*args):raise PermissionError('locked')
    monkeypatch.setattr('core.save.os.replace',fail)
    assert not service.save_image_pages([image()],str(target),PageOptions(),searchable=True)
    assert target.read_bytes()==b'OLD' and not list(tmp_path.glob('.versepic-*'))


def test_text_limits_reject_whole_page_instead_of_partial_hidden_payload():
    source=image()
    lines,warnings=positioned_lines(result(block('a'*500001)),source)
    assert lines==[] and warnings=={'text_limit':1}
    lines,warnings=positioned_lines({'code':100,'data':[block()]*5001},source)
    assert lines==[] and warnings=={'invalid_result':1}


def test_low_confidence_has_visible_report_without_raw_text(service,tmp_path,monkeypatch):
    mock_ocr(monkeypatch,result(block('Low score sample',score=.2)))
    report=PdfTextReport();assert service.save_image_pages([image()],str(tmp_path/'low.pdf'),PageOptions(),searchable=True,text_report=report)
    assert report.pages[0]['warnings']=={'low_confidence':1} and 'Low score sample' not in str(report.pages)


def test_real_ocr_thread_cancel_waits_and_cannot_commit_late(service,tmp_path,monkeypatch,qtbot):
    from ui.image_layout_dialog import ImageLayoutDialog
    started=threading.Event();release=threading.Event()
    monkeypatch.setattr('ocr.is_ocr_available',lambda:True)
    def recognize(*args,**kwargs):
        started.set();assert release.wait(10);return result()
    monkeypatch.setattr('ocr.recognize_text',recognize)
    dialog=ImageLayoutDialog(service.config_manager)
    target=tmp_path/'old.pdf';target.write_bytes(b'OLD')
    try:
        dialog.add_image('source',image());dialog.mode.setCurrentIndex(dialog.mode.findData('pdf'));dialog.searchable.setChecked(True)
        assert dialog.start_export(str(target));qtbot.waitUntil(started.is_set)
        dialog.cancel_job();assert dialog._worker is not None
        release.set();qtbot.waitUntil(lambda:dialog._worker is None)
        assert target.read_bytes()==b'OLD' and dialog._last_text_report is None
    finally:release.set();dialog.shutdown();dialog.close()


@pytest.mark.parametrize('language',['en','zh','ja','ko'])
def test_compiled_pdf_text_report_and_options(language):
    from PySide6.QtCore import QTranslator
    translator=QTranslator();main=Path(__file__).resolve().parents[1]
    assert translator.load(str(main/'translations'/f'app_{language}.qm'))
    for source in ('Searchable PDF (fresh local OCR)','PDF text report','Rotate PDF images','No text recognized',
                   'Missing font glyphs','Page %1: %2 text lines','Image-only page',
                   'PDF saved: %1 of %2 pages have searchable text. Review the PDF text report.'):
        assert translator.translate('ImageLayoutDialog',source),(language,source)
    assert translator.translate('TextRecognitionWindow','PDF output…')


def test_pdf_report_does_not_show_raw_ocr_text(qapp,service,monkeypatch):
    from ui.image_layout_dialog import ImageLayoutDialog
    dialog=ImageLayoutDialog(service.config_manager)
    dialog._last_text_report=PdfTextReport([{'page':1,'embedded_lines':0,'warnings':{'missing_glyphs':2},'image_only':True}])
    display=Mock();monkeypatch.setattr('ui.dialogs.show_text_dialog',display)
    dialog.show_pdf_report();assert 'Missing font glyphs: 2' in display.call_args.args[2]
    assert 'Image-only page' in display.call_args.args[2];dialog.close()


def test_row_and_page_order_not_changed_by_ocr_blocks(service,tmp_path,monkeypatch):
    data=iter([result(block('Page A')),result(block('Page B'))])
    monkeypatch.setattr('ocr.is_ocr_available',lambda:True);monkeypatch.setattr('ocr.recognize_text',lambda *a,**k:next(data))
    target=tmp_path/'order.pdf';assert service.save_image_pages([image(),image()],str(target),PageOptions(),searchable=True)
    pages=read_pdf(target);assert 'Page A' in pages[0][0] and 'Page B' in pages[1][0]
