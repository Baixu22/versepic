"""Rule false positives/negatives, explicit presets and irreversible raster output."""
from dataclasses import asdict
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QRect, QRectF, QSettings, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from settings.tool_settings import ToolSettingsManager
from text_recognition.redaction import (RedactionPresetStore, RedactionRules, numeric_candidates,
    redact_image, save_redacted_image, sensitive_lines, valid_bank_card, valid_china_id)
from text_recognition.redaction_window import RedactionWindow


def identity(prefix="11010519491231002"):
    weights=(7,9,10,5,8,4,2,1,6,3,7,9,10,5,8,4,2)
    return prefix+"10X98765432"[sum(int(x)*w for x,w in zip(prefix,weights,strict=True))%11]


def card(prefix="411111111111111"):
    for digit in "0123456789":
        if valid_bank_card(prefix+digit):return prefix+digit
    raise AssertionError("No Luhn digit")


def result(text,box=None):
    return {'data':[{'text':text,'box':box or [[10,10],[150,10],[150,35],[10,35]]}]}


def image(color='white'):
    out=QImage(240,100,QImage.Format.Format_ARGB32);out.fill(QColor(color));return out


@pytest.fixture
def config(tmp_path):
    return ToolSettingsManager(QSettings(str(tmp_path/'settings.ini'),QSettings.Format.IniFormat))


@pytest.fixture
def window(qapp,qtbot,monkeypatch,config):
    monkeypatch.setattr('settings.get_tool_settings_manager',lambda:config)
    thread=Mock()
    monkeypatch.setattr('text_recognition.redaction_window.recognize_async',lambda *a,**k:thread)
    import shiboken6
    value=RedactionWindow(image())
    yield value
    if shiboken6.isValid(value):value.close()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('value',[identity(),identity().lower(),identity('44010120000229001')])
def test_id_date_and_checksum_positive(value):
    assert valid_china_id(value.upper())
    found=sensitive_lines(result(value),image().rect(),phones=False,emails=False,china_ids=True)
    assert len(found)==1 and found[0][1]==QRect(7,7,146,31)


@pytest.mark.parametrize('value',[identity()[:-1]+'1',identity('99010519491231002'),identity('11010520230229001'),
    identity('11010529991231001'),identity('11010518991231001'),identity('11010519491231000'), '110105491231002'])
def test_id_invalid_checksum_date_region_sequence_and_legacy_not_matched(value):
    assert not valid_china_id(value)
    assert not sensitive_lines(result(value),image().rect(),phones=False,emails=False,china_ids=True)


@pytest.mark.parametrize('prefix',['411111111111','411111111111111','622202123456789012'])
def test_bank_13_16_19_digits_and_luhn(prefix):
    number=card(prefix)
    assert valid_bank_card(number)
    spaced=' '.join(number[i:i+4] for i in range(0,len(number),4))
    assert sensitive_lines(result('卡号：'+spaced),image().rect(),phones=False,emails=False,bank_cards=True)


@pytest.mark.parametrize('value',['4111111111111112','0000000000000000','1111111111111111','123456789012','41111111111111111111','x4111111111111111y'])
def test_bank_invalid_and_embedded_word_negative(value):
    assert not sensitive_lines(result(value),image().rect(),phones=False,emails=False,bank_cards=True)


@pytest.mark.parametrize('value',[identity().replace('0','O',1),identity().replace('1','l',1),identity().replace('1','I',1),identity().replace('1','|',1)])
def test_optional_ocr_substitutions_are_checksum_checked(value):
    assert not sensitive_lines(result(value),image().rect(),phones=False,emails=False,china_ids=True)
    assert sensitive_lines(result(value),image().rect(),phones=False,emails=False,china_ids=True,ocr_lookalikes=True)


def test_fullwidth_normalization_and_supported_separators():
    wide=''.join(chr(ord(c)+0xfee0) if c.isascii() and c.isalnum() else c for c in identity())
    assert sensitive_lines(result(wide),image().rect(),china_ids=True)
    assert list(numeric_candidates('4111-1111-1111-1111'))==['4111111111111111']


def test_rules_leave_known_false_negatives_explicit():
    # Not all OCR substitutions are safe: B/8 and S/5 are not guessed; split lines
    # cannot be joined without reliable glyph coordinates. Manual review is required.
    assert not sensitive_lines(result(identity().replace('5','S')),image().rect(),phones=False,emails=False,china_ids=True,ocr_lookalikes=True)
    assert not sensitive_lines({'data':[{'text':identity()[:9],'box':[[0,0],[90,0],[90,20],[0,20]]},
        {'text':identity()[9:],'box':[[0,30],[90,30],[90,50],[0,50]]}]},image().rect(),phones=False,emails=False,china_ids=True)
    assert not list(numeric_candidates('OOOOOOOOOOOOOOOO',lookalikes=True))
    assert not sensitive_lines(result(identity()),image().rect(),phones=False,emails=False)


def test_luhn_is_not_account_existence_or_business_identity():
    # A checksum-valid order number is still a candidate: user may uncheck it.
    assert sensitive_lines(result('Order: 4111111111111111'),image().rect(),phones=False,emails=False,bank_cards=True)


@pytest.mark.parametrize('block',[None,{'text':None},{'text':identity(),'box':[[float('inf'),0]]*4},
    {'text':identity(),'box':[['bad',0]]*4}])
def test_malformed_ocr_rows_cannot_crash_or_create_bad_rectangles(block):
    assert sensitive_lines({'data':[block]},image().rect(),china_ids=True)==[]


def test_preset_roundtrip_only_saves_name_and_flags(config):
    store=RedactionPresetStore(config)
    rules=RedactionRules(False,False,True,True,True)
    store.save('Financial',rules)
    persisted=RedactionPresetStore(ToolSettingsManager(QSettings(config.qsettings.fileName(),QSettings.Format.IniFormat)))
    assert persisted.load()==[{'version':1,'name':'Financial','rules':asdict(rules)}]
    store.delete('Financial');assert store.load()==[]


@pytest.mark.parametrize('name',['','x'*41,'line\nfeed','​hidden'])
def test_preset_names_rejected_without_writing(config,name):
    store=RedactionPresetStore(config)
    with pytest.raises(ValueError):store.save(name,RedactionRules())
    assert config.get_app_setting(store.KEY,'[]')=='[]'


def test_preset_duplicate_limit_and_unknown_delete_keep_data(config):
    store=RedactionPresetStore(config)
    for i in range(20):store.save(f'Rule {i}',RedactionRules())
    before=config.get_app_setting(store.KEY,'[]')
    with pytest.raises(ValueError):store.save('rule 0',RedactionRules())
    with pytest.raises(ValueError):store.save('Other',RedactionRules())
    with pytest.raises(ValueError):store.delete('missing')
    assert config.get_app_setting(store.KEY,'[]')==before


@pytest.mark.parametrize('raw',['bad','{}','['+'0,'*200+'0]',json.dumps([{'version':2,'name':'x','rules':asdict(RedactionRules())}]),
    json.dumps([{'version':1,'name':'x','rules':{'phones':'false'}}]),'x'*16001])
def test_invalid_saved_presets_preserved(config,raw):
    store=RedactionPresetStore(config);config.set_app_setting(store.KEY,raw)
    with pytest.raises((ValueError,TypeError)):store.save('safe',RedactionRules())
    assert config.get_app_setting(store.KEY,'')==raw


def test_failed_settings_write_restores_previous_flags():
    values={};qsettings=Mock();qsettings.status.return_value=QSettings.Status.AccessError
    config=SimpleNamespace(qsettings=qsettings,get_app_setting=lambda k,d:values.get(k,d),
                           set_app_setting=lambda k,v:values.__setitem__(k,v))
    with pytest.raises(OSError):RedactionPresetStore(config).save('x',RedactionRules())
    assert values[RedactionPresetStore.KEY]=='[]'


def test_preset_application_preserves_keywords_and_manual_review(window):
    window._recognized(result(identity()),'')
    assert window.candidates.count()==0
    window.presets.setCurrentIndex(2)
    assert window.candidates.count()==1
    window.candidates.item(0).setCheckState(Qt.CheckState.Unchecked)
    window._add_manual(QRect(180,20,20,20))
    window.keywords.setText('private-ephemeral')
    window.presets.setCurrentIndex(3)
    assert window.keywords.text()=='private-ephemeral'
    assert window.candidates.item(0).checkState()==Qt.CheckState.Unchecked
    assert window.selected_rectangles()==[QRect(180,20,20,20)]
    window.preset_store.save('safe',window.current_rules())
    assert 'private-ephemeral' not in window.config.get_app_setting(RedactionPresetStore.KEY,'')
    window.china_ids.setChecked(False)
    assert window.presets.currentIndex()==0 and window.selected_rectangles()==[QRect(180,20,20,20)]


def test_delete_preset_confirmation_does_not_change_current_rules(window,monkeypatch):
    window.preset_store.save('saved',RedactionRules(china_ids=True));window._load_presets('saved')
    window._apply_preset();before=window.current_rules()
    monkeypatch.setattr('text_recognition.redaction_window.show_confirm_dialog',lambda *a,**k:False)
    window._delete_preset();assert window.preset_store.load()
    monkeypatch.setattr('text_recognition.redaction_window.show_confirm_dialog',lambda *a,**k:True)
    window._delete_preset();assert not window.preset_store.load() and window.current_rules()==before


def test_late_ocr_result_after_close_is_ignored(window):
    window.close()
    window._recognized(result(identity()),'')
    assert window._result=={'data':[]}


def test_save_refuses_original_file(config,tmp_path):
    source=tmp_path/'original.png';assert image().save(str(source));before=source.read_bytes()
    with pytest.raises(FileExistsError):save_redacted_image(image(),[QRect(10,10,20,20)],str(source),config)
    assert source.read_bytes()==before


def test_atomic_redaction_failure_removes_only_reserved_placeholder(config,tmp_path,monkeypatch):
    source=tmp_path/'keep.png';source.write_bytes(b'unchanged')
    monkeypatch.setattr('core.save.SaveService._save_qimage_to_path',lambda *a,**k:False)
    assert not save_redacted_image(image(),[QRect(10,10,20,20)],str(tmp_path/'new.png'),config)
    assert list(tmp_path.glob('*.png'))==[source] and source.read_bytes()==b'unchanged'
    assert not list(tmp_path.glob('.versepic-*'))


@pytest.mark.parametrize('extension',['png','jpg','pdf'])
def test_export_hidden_source_pixels_never_affect_output_and_has_no_text_layer(config,tmp_path,extension):
    from PySide6.QtPdf import QPdfDocument
    from PIL import Image
    a=image();b=image();rect=QRect(32,16,128,48)
    for base,color in ((a,'red'),(b,'blue')):
        painter=QPainter(base);painter.fillRect(rect,QColor(color));painter.end()
        base.setText('Secret','RAW_PRIVATE_TEXT');base.setDevicePixelRatio(2)
    # Global screenshot downsampling must not alter the reviewed mask coordinates.
    config.set_app_setting('screenshot_size_mode','half')
    paths=[tmp_path/f'{name}.{extension}' for name in ('a','b')]
    for original,path in zip((a,b),paths,strict=True):assert save_redacted_image(original,[rect],str(path),config)
    if extension=='pdf':
        rendered=[]
        for path in paths:
            doc=QPdfDocument();assert doc.load(str(path))==QPdfDocument.Error.None_
            assert doc.pageCount()==1 and doc.getAllText(0).text()==''
            rendered.append(doc.render(0,QSize(240,100)));doc.close()
        assert rendered[0]==rendered[1]
        assert rendered[0].pixelColor(90,40)==QColor('black')
    else:
        assert paths[0].read_bytes()==paths[1].read_bytes()
        with Image.open(paths[0]) as encoded:
            assert encoded.size==(240,100) and 'RAW_PRIVATE_TEXT' not in str(encoded.info)
            assert encoded.convert('RGB').getpixel((90,40))==(0,0,0)
    assert a.pixelColor(90,40)==QColor('red') and b.pixelColor(90,40)==QColor('blue')
    assert a.text('Secret')=='RAW_PRIVATE_TEXT'


def test_fractional_clipped_mask_has_opaque_black_boundary_and_no_metadata():
    source=image('transparent');source.setText('Secret','private')
    out=redact_image(source,[QRectF(-.5,2.2,30.6,10.4)])
    assert not out.textKeys() and out.devicePixelRatio()==1
    for y in range(2,13):
        for x in range(31):assert out.pixelColor(x,y)==QColor('black')
    assert source.pixelColor(10,5).alpha()==0


def test_history_and_capture_use_same_redaction_ui(qapp,monkeypatch):
    from clipboard.ui.windows.clipboard_window import ClipboardWindow
    from tools.action import ActionTools
    from PySide6.QtCore import QByteArray,QBuffer,QIODevice
    source=image();array=QByteArray();buffer=QBuffer(array);buffer.open(QIODevice.OpenModeFlag.WriteOnly);source.save(buffer,'PNG')
    manager=Mock();manager.get_item.return_value=SimpleNamespace(image_id='fixture');manager.get_image_data.return_value=bytes(array)
    owner=SimpleNamespace(manager=manager)
    shown=[];monkeypatch.setattr('text_recognition.redaction_window.show_redaction',shown.append)
    ClipboardWindow._process_image(owner,17,redact=True)
    tools=ActionTools.__new__(ActionTools);tools.scene=Mock();tools.scene.selection_model.is_confirmed=True
    tools.scene.selection_model.rect.return_value=QRectF(source.rect());tools.export_service=Mock();tools.export_service.export.return_value=source
    tools._remember_last_region=Mock();tools._cleanup_and_close=Mock();tools.handle_smart_redact()
    assert shown==[source,source]
    manager.update_item.assert_not_called()


def test_close_releases_review_window(window,qapp):
    import shiboken6
    window.close();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(window)


@pytest.mark.parametrize('data',[None,42,{'text':'not a row list'},'wrong'])
def test_malformed_ocr_collection_is_ignored(data):
    assert sensitive_lines({'data':data},image().rect(),china_ids=True)==[]


def test_existing_hardlink_alias_cannot_be_overwritten(config,tmp_path):
    import os
    original=tmp_path/'original.png';original.write_bytes(b'PRIVATE SOURCE')
    alias=tmp_path/'alias.png';os.link(original,alias)
    with pytest.raises(FileExistsError):save_redacted_image(image(),[QRect(2,2,10,10)],str(alias),config)
    assert original.read_bytes()==b'PRIVATE SOURCE' and alias.read_bytes()==b'PRIVATE SOURCE'


@pytest.mark.parametrize('language',['en','zh','ja','ko'])
def test_compiled_rule_translations_are_complete(language):
    import ast
    from pathlib import Path
    from PySide6.QtCore import QTranslator
    main=Path(__file__).resolve().parents[1]
    translator=QTranslator();assert translator.load(str(main/'translations'/f'app_{language}.qm'))
    tree=ast.parse((main/'text_recognition'/'redaction_window.py').read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='_tr' and node.args and isinstance(node.args[0],ast.Constant):
            assert translator.translate('RedactionWindow',node.args[0].value),(language,node.args[0].value)


def test_empty_mask_and_unsupported_format_do_not_create_files(config,tmp_path):
    for suffix,rects in [('png',[]),('vpic',[QRect(2,2,10,10)])]:
        target=tmp_path/('invalid.'+suffix)
        with pytest.raises(ValueError):save_redacted_image(image(),rects,str(target),config)
        assert not target.exists()


def test_bank_ocr_confusion_still_requires_luhn():
    confused='4I11 1111 1111 1111'
    assert not sensitive_lines(result(confused),image().rect(),phones=False,emails=False,bank_cards=True)
    assert sensitive_lines(result(confused),image().rect(),phones=False,emails=False,bank_cards=True,ocr_lookalikes=True)
    assert not sensitive_lines(result('4I11 1111 1111 1112'),image().rect(),phones=False,emails=False,bank_cards=True,ocr_lookalikes=True)


def test_rule_switches_and_close_do_not_implicitly_save_settings(window):
    before=window.config.get_app_setting(RedactionPresetStore.KEY,'[]')
    window.presets.setCurrentIndex(3);window.ocr_lookalikes.setChecked(True);window.keywords.setText('private')
    window.close()
    assert window.config.get_app_setting(RedactionPresetStore.KEY,'[]')==before
