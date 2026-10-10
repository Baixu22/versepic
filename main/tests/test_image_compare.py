"""Read-only comparison, precise pixel/coverage semantics and view synchronization."""
from pathlib import Path
from types import SimpleNamespace
import random
import threading

import pytest
from PySide6.QtCore import QBuffer,QIODevice,QPoint,QPointF,QSize,Qt
from PySide6.QtGui import QColor,QImage,QPainter

from core.image_compare import CompareCancelled,CompareError,difference_overlay,validate_pair
from ui.image_compare import ImageCompareWindow


def image(color="red",width=100,height=80):
    result=QImage(width,height,QImage.Format.Format_RGBA8888);result.fill(QColor(color));return result


def encoded(image):
    buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);assert image.save(buffer,"PNG")
    return bytes(buffer.data())


def test_identical_images_have_no_overlay_and_do_not_change_inputs():
    first=image();second=QImage(first)
    result=difference_overlay(first,second)
    assert result.changed_pixels==0 and result.compared_pixels==8000
    assert result.overlay.pixelColor(10,10).alpha()==0
    assert first==second and first.pixelColor(10,10).name()=="#ff0000"


def test_single_pixel_change_and_threshold_boundary_are_exact():
    first=image("#112233");second=QImage(first);second.setPixelColor(2,3,QColor("#112244"))
    result=difference_overlay(first,second,threshold=16)
    assert result.changed_pixels==1
    assert result.overlay.pixelColor(2,3).alpha()==180
    assert result.overlay.pixelColor(3,3).alpha()==0
    assert difference_overlay(first,second,threshold=17).changed_pixels==0


def test_invisible_rgb_is_ignored_but_alpha_is_compared():
    a=image("#00112233");b=image("#00aabbcc")
    assert difference_overlay(a,b).changed_pixels==0
    b.setPixelColor(4,5,QColor(17,34,51,128))
    assert difference_overlay(a,b).changed_pixels==1
    assert difference_overlay(a,b,threshold=128).changed_pixels==0


def test_missing_coverage_is_difference_even_if_transparent_and_threshold_255():
    a=image("transparent",10,20);b=image("transparent",20,10)
    result=difference_overlay(a,b,threshold=255)
    assert result.overlay.size()==QSize(20,20)
    assert result.changed_pixels==200 and result.compared_pixels==400
    assert result.overlay.pixelColor(0,15).alpha()>0
    assert result.overlay.pixelColor(15,15).alpha()==0  # Neither source covers this part of union rectangle.


def test_explicit_resize_b_to_a_changes_the_comparison_geometry():
    a=image("red",40,30);b=image("red",20,15)
    assert difference_overlay(a,b).changed_pixels==900
    assert difference_overlay(a,b,"scale_b").changed_pixels==0
    assert b.size()==QSize(20,15)


def test_overlay_matches_reference_over_multiple_stripes():
    a=image("#203040",350,520);b=QImage(a)
    points=set()
    rng=random.Random(22)
    for _ in range(800):points.add((rng.randrange(350),rng.randrange(520)))
    for x,y in points:b.setPixelColor(x,y,QColor("white"))
    result=difference_overlay(a,b)
    assert result.changed_pixels==len(points)
    for x,y in points:assert result.overlay.pixelColor(x,y).alpha()==180


@pytest.mark.parametrize("threshold",[-1,256,1.5,True,"1"])
def test_invalid_threshold_fails_before_processing(threshold):
    with pytest.raises(CompareError):difference_overlay(image(),image(),threshold=threshold)


def test_union_budget_rejects_wide_and_tall_pair_without_huge_allocation():
    with pytest.raises(CompareError):validate_pair(image(width=10000,height=1),image(width=1,height=10000))
    with pytest.raises(CompareError):validate_pair(QImage(),image())
    with pytest.raises(CompareError):validate_pair(image(),image(),"unknown")


def test_cancellation_is_checked_between_bounded_stripes():
    calls=[0]
    def cancel():calls[0]+=1;return calls[0]>=3
    with pytest.raises(CompareCancelled):difference_overlay(image(width=100,height=800),image("blue",100,800),cancelled=cancel)
    assert calls[0]==3


@pytest.fixture
def window(qapp):
    compare=ImageCompareWindow();compare.show()
    yield compare
    import shiboken6
    if shiboken6.isValid(compare):
        compare.shutdown();compare.close()


def load_pair(window,first=None,second=None):
    assert window.set_image(0,first if first is not None else image(),"A")
    assert window.set_image(1,second if second is not None else image("blue"),"B")


def test_load_swap_clear_and_input_ownership(window):
    a=image();load_pair(window,a)
    a.fill(QColor("green"))
    assert window.images[0].pixelColor(0,0).name()=="#ff0000"
    assert window.slot.currentData()==1
    window.swap();assert window.names==["B","A"]
    assert window.images[0].pixelColor(0,0).name()=="#0000ff"
    window.clear();assert window.images==[None,None] and window.result is None and window.canvas_rect.isEmpty()


def test_file_history_pin_sources_keep_old_images_when_replacement_missing(window,tmp_path):
    file=tmp_path/"one.png";image().save(str(file));before=file.read_bytes()
    assert window.load_file(str(file),0)
    assert file.read_bytes()==before
    assert not window.load_file(str(tmp_path/"missing.png"),0)
    assert window.names[0]=="one.png"
    record=SimpleNamespace(content_type="image",image_id="x",title="History",id=7)
    manager=SimpleNamespace(get_item=lambda _:record,get_image_data=lambda _:encoded(image("blue")))
    assert window.load_history(manager,7,1)
    pin=SimpleNamespace(_is_closed=False,canvas=SimpleNamespace(base_size=QSize(100,80)),devicePixelRatioF=lambda:1,
                        get_current_image=lambda:image("yellow"),_with_edit_paused=lambda callback:callback())
    assert window.load_pin(pin,1)
    pin._is_closed=True
    assert not window.load_pin(pin,1)
    assert window.images[1].pixelColor(0,0).name()=="#ffff00"


def test_image_limit_rejects_pair_without_replacing_existing(window):
    load_pair(window,image(width=10000,height=1),image(width=100,height=1))
    before=window.images[1]
    assert not window.set_image(1,image(width=1,height=10000),"Too tall")
    assert window.images[1]==before


def test_worker_difference_count_and_parameter_change(window,qtbot):
    load_pair(window)
    window.mode.setCurrentIndex(2)
    qtbot.waitUntil(lambda:window.result is not None,timeout=10000)
    assert window.result.changed_pixels==8000
    window.threshold.setValue(255)
    assert window.result is None
    qtbot.waitUntil(lambda:window.result is not None)
    assert window.result.changed_pixels==0


def test_late_worker_cannot_publish_stale_pair(window,qtbot,monkeypatch):
    import ui.image_compare as module
    from core.image_compare import DifferenceResult
    entered,release=threading.Event(),threading.Event();original=module.difference_overlay
    first=[True]
    def delayed(*args,**kwargs):
        if first[0]:
            first[0]=False;entered.set();assert release.wait(5)
            return DifferenceResult(image("magenta"),123,8000)  # even a late result ignoring cancellation is rejected
        return original(*args,**kwargs)
    monkeypatch.setattr(module,"difference_overlay",delayed)
    load_pair(window);window.mode.setCurrentIndex(2)
    qtbot.waitUntil(entered.is_set)
    window.set_image(1,image(),"same as A")
    release.set()
    qtbot.waitUntil(lambda:window.result is not None)
    assert window.result.changed_pixels==0 and window.names[1]=="same as A"


def test_sync_zoom_and_pan_preserve_same_scene_center(window,qtbot):
    load_pair(window,image(width=1800,height=1200),image("blue",1800,1200))
    qtbot.waitUntil(lambda:window.views[0].viewport().width()>100)
    window.set_zoom(2)
    assert all(abs(view.transform().m11()-2)<1e-9 for view in window.views)
    window.views[0].centerOn(QPointF(700,600))
    a=window.views[0].mapToScene(window.views[0].viewport().rect().center())
    b=window.views[1].mapToScene(window.views[1].viewport().rect().center())
    assert abs(a.x()-b.x())<=1 and abs(a.y()-b.y())<=1
    window.fit();assert window._fit


def render_item(window,index=0):
    rect=window.canvas_rect
    output=QImage(int(rect.width()),int(rect.height()),QImage.Format.Format_ARGB32)
    output.fill(0);painter=QPainter(output);window.views[index].item.paint(painter,None);painter.end()
    return output


def test_wipe_displays_a_left_and_b_right_using_slider(window):
    load_pair(window);window.mode.setCurrentIndex(1);window.split.setValue(25)
    result=render_item(window)
    assert result.pixelColor(10,40).name()=="#ff0000"
    assert result.pixelColor(80,40).name()=="#0000ff"
    window.split.setValue(75);result=render_item(window)
    assert result.pixelColor(60,40).name()=="#ff0000"
    assert window.images[0].pixelColor(80,40).name()=="#ff0000"


def test_difference_overlay_draws_only_changed_region(window,qtbot):
    first=image("white");second=QImage(first);second.setPixelColor(10,20,QColor("black"))
    load_pair(window,first,second);window.mode.setCurrentIndex(2)
    qtbot.waitUntil(lambda:window.result is not None)
    painted=render_item(window)
    assert painted.pixelColor(11,20).name()=="#ffffff"
    assert painted.pixelColor(10,20)!=QColor("black")


def test_read_only_file_dialog_cancel_leaves_pair_untouched(window,monkeypatch):
    load_pair(window);before=list(window.images)
    monkeypatch.setattr("ui.image_compare.QFileDialog.getOpenFileName",lambda *a:("",""))
    window.choose_file();assert window.images==before


def test_close_waits_for_worker_then_releases_window_and_images(qapp,qtbot,monkeypatch):
    import shiboken6
    import ui.image_compare as module
    entered,release=threading.Event(),threading.Event();original=module.difference_overlay
    def delayed(*a,**kw):entered.set();assert release.wait(5);return original(*a,**kw)
    monkeypatch.setattr(module,"difference_overlay",delayed)
    window=ImageCompareWindow();window.show();load_pair(window);window.mode.setCurrentIndex(2)
    qtbot.waitUntil(entered.is_set)
    window.close();assert window._worker is not None and window._closing
    release.set()
    qtbot.waitUntil(lambda:not shiboken6.isValid(window))


COMPARE_MESSAGES={
  "ImageCompareWindow": [
    "Image A",
    "Image B",
    "Image Comparison",
    "Replace image A",
    "Replace image B",
    "Original pixels, align top-left",
    "Resize B to A (may distort)",
    "Pixel difference threshold",
    "Threshold",
    "Fit",
    "Read-only comparison. Original pixels align at the top-left; missing areas are differences. Wheel zooms both views; drag pans. Resizing B may introduce interpolation differences. Pixel differences are not a correctness verdict.",
    "A / B split position",
    "Choose two images to compare. No source files are changed.",
    "Could not load image: missing data, unsupported format or comparison limit (32 megapixels total). Existing images were kept.",
    "Choose comparison image",
    "History image %1",
    "Pinned image",
    "Comparison canvas exceeds 32 megapixels. Use another image pair or resize B to A.",
    "Comparing pixels…",
    "%1 of %2 pixels differ (%3%). Alpha is compared; invisible RGB is ignored.",
    "Read-only · %1 × %2 comparison pixels · A on the left, B on the right.",
    "Comparison failed. Reduce image sizes or choose another pair.",
    "Choose file…",
    "Choose history image…",
    "Choose pinned image…",
    "Swap A / B",
    "Clear images",
    "Side by side",
    "Slider comparison",
    "Difference overlay"
  ],
  "SystemTray": [
    "Compare images…"
  ],
  "PinWindow": [
    "Compare image…"
  ],
  "ClipboardWindow": [
    "Compare image…"
  ]
}

@pytest.mark.parametrize("lang",["en","zh","ja","ko"])
def test_compiled_comparison_strings(qapp,lang):
    from PySide6.QtCore import QTranslator
    tr=QTranslator()
    assert tr.load(str(Path(__file__).resolve().parents[1]/"translations"/f"app_{lang}.qm"))
    for context,sources in COMPARE_MESSAGES.items():
        for text in sources:assert tr.translate(context,text),(lang,context,text)


def test_alpha_visible_color_threshold_is_independent_of_unused_rgb():
    a=image("#80402010",12,8);b=image("#80402010",12,8)
    b.setPixelColor(2,2,QColor(65,32,16,128))
    result=difference_overlay(a,b)
    # Premultiplied channels can round an unobservable one-level color difference.
    ar=a.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
    br=b.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
    expected=int(ar.pixel(2,2)!=br.pixel(2,2))
    assert result.changed_pixels==expected


def test_canvas_too_large_after_switching_alignment_is_reported(window,qtbot):
    window.alignment.setCurrentIndex(1)
    load_pair(window,image(width=10000,height=1),image(width=1,height=10000))
    window.alignment.setCurrentIndex(0)
    assert window.canvas_rect.isEmpty() and window._invalid_geometry
    assert "32" in window.status.text()
    window.mode.setCurrentIndex(2)
    qtbot.wait(120)
    assert window._worker is None and window.result is None
    window.alignment.setCurrentIndex(1)
    qtbot.waitUntil(lambda:window.result is not None)
    assert window.canvas_rect.size().toSize()==QSize(10000,1)


def test_clearing_while_comparing_never_repopulates_old_result(window,qtbot,monkeypatch):
    import ui.image_compare as module
    entered,release=threading.Event(),threading.Event();original=module.difference_overlay
    def delayed(*args,**kwargs):
        entered.set();assert release.wait(5)
        return original(*args,**kwargs)
    monkeypatch.setattr(module,"difference_overlay",delayed)
    load_pair(window);window.mode.setCurrentIndex(2);qtbot.waitUntil(entered.is_set)
    window.clear();release.set();qtbot.waitUntil(lambda:window._worker is None)
    assert window.images==[None,None] and window.result is None and window.canvas_rect.isEmpty()


def test_slider_boundary_is_draggable_in_image_coordinates(window,qtbot):
    load_pair(window);window.mode.setCurrentIndex(1)
    qtbot.wait(30);window.fit()
    view=window.views[0]
    start=view.mapFromScene(QPointF(50,40));end=view.mapFromScene(QPointF(75,40))
    qtbot.mousePress(view.viewport(),Qt.MouseButton.LeftButton,pos=start)
    qtbot.mouseMove(view.viewport(),end)
    qtbot.mouseRelease(view.viewport(),Qt.MouseButton.LeftButton,pos=end)
    assert abs(window.split.value()-75)<=1
    assert not view._wiping


def test_pin_comparison_keeps_annotation_and_transform_state(qapp,window,tmp_settings):
    from settings.tool_settings import ToolSettingsManager
    from pin.pin_manager import PinManager
    from tests.test_editable_project import populate,pixels
    from PySide6.QtCore import QPoint
    config=ToolSettingsManager(tmp_settings);config.set_ocr_enabled(False)
    manager=PinManager.instance()
    pin=manager.create_pin(image("#ddddee",480,360),QPoint(80,80),config)
    try:
        populate(pin.canvas);pin.rotate_image_cw();pin.flip_image_vertical()
        before=pixels(pin.get_current_image());count=len(pin.canvas.scene.items())
        assert window.load_pin(pin,0)
        assert len(pin.canvas.scene.items())==count
        assert pin._image_transform.rotation==90 and pin._image_transform.flip_v
        assert pixels(window.images[0])==before
        assert pixels(pin.get_current_image())==before
    finally:pin.close_window()


def test_history_context_action_forwards_to_public_compare_window(monkeypatch):
    from clipboard.ui.windows.clipboard_window import ClipboardWindow
    from unittest.mock import Mock
    target=Mock();owner=SimpleNamespace(close=Mock(),manager=object())
    monkeypatch.setattr("ui.image_compare.show_image_compare",lambda:target)
    ClipboardWindow._compare_image(owner,17)
    owner.close.assert_called_once()
    target.load_history.assert_called_once_with(owner.manager,17)


def test_dpr_image_not_modified_and_difference_remains_pixel_based(window):
    first=image("red",60,40);first.setDevicePixelRatio(2)
    load_pair(window,first,image("red",60,40))
    assert first.devicePixelRatio()==2
    assert all(im.devicePixelRatio()==1 for im in window.images)
    assert difference_overlay(*window.images).changed_pixels==0


def test_difference_failure_is_visible_and_does_not_spin_retry(window,qtbot,monkeypatch):
    from unittest.mock import Mock
    failing=Mock(side_effect=MemoryError("budget"))
    monkeypatch.setattr("ui.image_compare.difference_overlay",failing)
    load_pair(window);window.mode.setCurrentIndex(2)
    qtbot.waitUntil(lambda:window._result_revision==window._revision)
    qtbot.wait(160)
    assert window.result is None and window._worker is None and failing.call_count==1
    assert "failed" in window.status.text().lower()


def test_single_view_names_both_sources_and_swap_keeps_labels_truthful(window):
    load_pair(window)
    window.mode.setCurrentIndex(2)
    assert window.names[0] in window.labels[0].text() and window.names[1] in window.labels[0].text()
    assert "↔" in window.labels[0].text()
    window.swap()
    assert window.labels[0].text().index(" · B")<window.labels[0].text().index(" · A")
    window.mode.setCurrentIndex(0)
    assert window.labels[0].text().startswith("A · B")
    assert window.labels[1].text().startswith("B · A")


def test_repeated_open_compare_clear_close_releases_all_windows(qapp,qtbot):
    import shiboken6
    from PySide6.QtCore import QCoreApplication,QEvent
    for _ in range(4):
        window=ImageCompareWindow();window.show();load_pair(window)
        window.mode.setCurrentIndex(2);qtbot.waitUntil(lambda window=window:window.result is not None)
        window.close()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        assert not shiboken6.isValid(window)
    assert not any(isinstance(widget,ImageCompareWindow) for widget in qapp.allWidgets())


def test_visible_alpha_color_matches_independent_premultiplied_reference():
    a=image("transparent",27,19);b=image("transparent",27,19)
    rng=random.Random(812)
    for y in range(19):
        for x in range(27):
            a.setPixelColor(x,y,QColor(*(rng.randrange(256) for _ in range(4))))
            b.setPixelColor(x,y,QColor(*(rng.randrange(256) for _ in range(4))))
    result=difference_overlay(a,b,threshold=80)
    def premultiplied(color):
        r,g,b,alpha=color.getRgb()
        return (round(r*alpha/255),round(g*alpha/255),round(b*alpha/255),alpha)
    expected=0
    for y in range(19):
        for x in range(27):
            differs=max(abs(i-j) for i,j in zip(premultiplied(a.pixelColor(x,y)),premultiplied(b.pixelColor(x,y))))>80
            expected+=differs
            assert (result.overlay.pixelColor(x,y).alpha()>0)==differs
    assert result.changed_pixels==expected


def test_transparent_and_rgb_formats_have_identical_visible_semantics():
    a=image("blue");b=a.convertToFormat(QImage.Format.Format_RGB888)
    assert difference_overlay(a,b).changed_pixels==0


def test_original_source_views_remain_read_only_under_drag(window,qtbot):
    load_pair(window);qtbot.wait(30)
    before=[QImage(im) for im in window.images]
    view=window.views[0];point=view.viewport().rect().center()
    qtbot.mousePress(view.viewport(),Qt.MouseButton.LeftButton,pos=point)
    qtbot.mouseMove(view.viewport(),point+QPoint(20,20))
    qtbot.mouseRelease(view.viewport(),Qt.MouseButton.LeftButton,pos=point)
    assert window.images==before


def test_named_source_is_plain_text_not_html(window):
    assert window.set_image(0,image(),'<img src="file:///private.png">')
    assert window.labels[0].textFormat()==Qt.TextFormat.PlainText


def test_resize_alignment_overlay_and_display_use_same_pixels(window,qtbot):
    second=image("blue",13,9)
    second.setPixelColor(6,4,QColor("red"))
    first=second.scaled(49,31,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
    window.alignment.setCurrentIndex(1);load_pair(window,first,second)
    window.mode.setCurrentIndex(2);qtbot.waitUntil(lambda:window.result is not None)
    assert window.result.changed_pixels==0
    rendered=render_item(window).convertToFormat(QImage.Format.Format_ARGB32)
    expected=first.convertToFormat(QImage.Format.Format_ARGB32)
    assert rendered==expected
