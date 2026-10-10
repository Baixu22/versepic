"""
导出服务
统一的图像导出接口
"""

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter, QPixmap

from core import log_debug, log_warning, T
from core.number_legend import LegendOptions, collect_entries, normalize_placement, render as render_legend


class ExportService:
    """
    导出服务 - 统一处理图像导出
    """
    
    def __init__(self, scene):
        """
        Args:
            scene: CanvasScene 实例
        """
        self.scene = scene
    
    def get_result_pixmap(self) -> QPixmap:
        """
        获取最终结果图像 (选区内容)
        """
        # 获取选区
        selection_rect = self.scene.selection_model.rect()
        if selection_rect.isEmpty():
            # 如果没有选区，导出整个场景
            selection_rect = self.scene.sceneRect()
            
        return QPixmap.fromImage(self.export(selection_rect))

    def export(self, selection_rect: QRectF) -> QImage:
        """
        导出选区图像（包含背景和绘制内容）
        
        Args:
            selection_rect: 选区矩形（场景坐标）
            
        Returns:
            导出的图像
        """
        if selection_rect.isNull() or selection_rect.isEmpty():
            log_warning(T("选区为空"), "Export")
            return QImage()

        # 输出图像大小按选区逻辑像素
        w = max(1, int(selection_rect.width()))
        h = max(1, int(selection_rect.height()))

        log_debug(T("导出选区: {selection_rect}, 目标大小: {w}x{h}", selection_rect=selection_rect, w=w, h=h), "Export")
        
        out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(0)  # 透明背景
        
        painter = QPainter(out)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            
            # 选区框和遮罩都已移出场景（各自的 QWidget 叠层），
            # 场景里只剩背景和绘图内容，直接渲染即可
            self.scene.render(painter, QRectF(0, 0, w, h), selection_rect)
        finally:
            painter.end()
        
        log_debug(T("导出完成: {out_width}x{out_height}", out_width=out.width(), out_height=out.height()), "Export")
        return out
    
    def legend_placement(self) -> str:
        """读取"导出时附带编号说明"的位置设置；默认不附带，老行为不变。"""
        try:
            from settings import get_tool_settings_manager

            manager = get_tool_settings_manager()
            raw = manager.get_app_setting("number_legend_placement", "off") if manager else "off"
        except Exception as exc:
            log_warning(T("读取编号说明设置失败: {exc}", exc=exc), "Export")
            raw = "off"
        return normalize_placement(raw)

    def export_with_legend(self, selection_rect: QRectF, options: LegendOptions = None) -> QImage:
        """最终导出链：成图 → 水印（可选，默认关）→ 编号说明（可选，默认关）。"""
        image = self.export(selection_rect)
        if image.isNull():
            return image
        from core.watermark import load_options, render as render_watermark

        image = render_watermark(image, load_options())
        from dataclasses import replace

        from core.capture_metadata import load_metadata, now_stamp, render_strip

        metadata = load_metadata()
        if metadata.time_enabled and not metadata.captured_at:
            metadata = replace(metadata, captured_at=now_stamp())
        image = render_strip(image, metadata.build_lines())
        if options is None:
            options = LegendOptions(placement=self.legend_placement())
        entries = collect_entries(self.scene.items())
        return render_legend(image, entries, options)

    def export_base_image_only(self, selection_rect: QRectF) -> QImage:
        """
        导出选区的纯净底图（不包含任何绘制内容）
        用于钉图功能，保证钉图可以继续编辑绘制内容
        
        Args:
            selection_rect: 选区矩形（场景坐标）
            
        Returns:
            只包含背景的图像
        """
        if selection_rect.isNull() or selection_rect.isEmpty():
            log_warning(T("选区为空"), "Export")
            return QImage()

        # 输出图像大小按选区逻辑像素
        w = max(1, int(selection_rect.width()))
        h = max(1, int(selection_rect.height()))

        log_debug(T("导出底图: {selection_rect}, 目标大小: {w}x{h}", selection_rect=selection_rect, w=w, h=h), "Export")
        
        out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(0)  # 透明背景
        
        painter = QPainter(out)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            
            # 只渲染背景层，隐藏所有非背景图层
            old_visible_states = []
            for item in self.scene.items():
                if item != self.scene.background:
                    old_visible_states.append((item, item.isVisible()))
                    item.setVisible(False)
            
            # 只渲染背景
            self.scene.render(painter, QRectF(0, 0, w, h), selection_rect)
            
            # 恢复所有图层的可见性
            for item, visible in old_visible_states:
                item.setVisible(visible)
                
        finally:
            painter.end()
        
        log_debug(T("导出底图完成: {out_width}x{out_height}", out_width=out.width(), out_height=out.height()), "Export")
        return out
    

 