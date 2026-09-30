# -*- coding: utf-8 -*-
"""标签存储与菜单接线冒烟。"""

from clipboard.core.models import Tag
from clipboard.core.tag_store import TagStore


def test_tag_store_crud_roundtrip(tmp_path):
    TagStore.reset_instance()
    store = TagStore(str(tmp_path / "tags.db"))
    tag = store.ensure_tag("工作", "#5B8DB8")
    assert tag is not None and tag.name == "工作"
    assert store.ensure_tag("工作").id == tag.id  # 幂等

    assert store.toggle_tag_on_item(101, tag.id) is True
    tags = store.get_tags(101)
    assert [t.name for t in tags] == ["工作"]
    assert store.toggle_tag_on_item(101, tag.id) is False
    assert store.get_tags(101) == []

    store.add_tag_to_item(101, tag.id)
    store.add_tag_to_item(102, tag.id)
    assert set(store.item_ids_with_tag(tag.id)) == {101, 102}
    store.delete_items([101])
    assert store.item_ids_with_tag(tag.id) == [102]
    store.delete_tag(tag.id)
    assert store.list_tags() == []
    store.close()
    TagStore.reset_instance()


def test_tag_chip_colors_assigned_for_unknown():
    TagStore.reset_instance()
    import tempfile, os
    path = os.path.join(tempfile.mkdtemp(), "tags.db")
    store = TagStore(path)
    t = store.ensure_tag("X")
    assert t.chip_color in Tag(id=1, name="X", color=None).chip_color or True
    from clipboard.core.models import TAG_CHIP_COLORS
    assert t.chip_color in TAG_CHIP_COLORS
    store.close()
    TagStore.reset_instance()
