from pathlib import Path

import app as app_module
from services import tips_content


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_comment_image_upload_has_preview_and_removal_support():
    script = _read("static/js/markdown-image-paste.js")
    assert "comment-image-preview" in script
    assert "이미지 제거" in script
    assert "community-comment-list" in script
    assert "imagePastePurpose" in script


def test_all_post_editors_use_the_shared_wysiwyg_assets():
    templates = (
        "templates/community_board.html",
        "templates/community_post_edit.html",
        "templates/diary_board.html",
        "templates/diary_edit.html",
        "templates/work_notes/form.html",
        "templates/tips/form.html",
        "templates/action_items.html",
        "templates/action_item_detail.html",
    )
    for template_path in templates:
        template = _read(template_path)
        assert "data-wysiwyg-editor" in template, template_path
        assert '_wysiwyg_editor_head.html' in template, template_path
        assert '_wysiwyg_editor_scripts.html' in template, template_path

    work_note = _read("templates/work_notes/form.html")
    assert "data-markdown-preview" not in work_note
    assert "data-work-note-preview-dialog" not in work_note
    assert 'data-editor-context="work-note"' in work_note


def test_editor_uses_markdown_storage_slash_search_and_existing_upload_api():
    script = _read("static/js/wysiwyg-editor.js")
    assert 'initialEditType: "wysiwyg"' in script
    assert 'hideModeSwitch: true' in script
    assert 'language: "ko-KR"' in script
    assert "editor.getMarkdown()" in script
    assert "editor.getHTML()" not in script
    assert "source.hidden = true" in script
    assert 'source.setAttribute("aria-hidden", "true")' in script
    assert 'field.tagName === "LABEL"' in script
    assert "field.parentNode.replaceChild(fieldWrapper, field)" in script
    assert "field.parentNode.insertBefore(source, field.nextSibling)" not in script
    assert 'event.target.closest(".toastui-editor-ww-container .ProseMirror")' in script
    assert "hideEditorPopups();" in script
    assert 'addImageBlobHook' in script
    assert 'payload.append("csrf_token"' in script
    assert 'payload.append("scope"' in script
    assert 'credentials: "same-origin"' in script
    assert 'event.key === "ArrowDown"' in script
    assert 'event.key === "ArrowUp"' in script
    assert 'event.key === "Enter"' in script
    assert 'event.key === "Escape"' in script
    assert "toLocaleLowerCase" in script
    assert "applyBlockMarkdownShortcut" in script
    assert "applyInlineMarkdownShortcut" in script
    assert 'editor.exec("addTable", { rowCount: 3, columnCount: 3 })' in script
    for command in (
        "text", "h1", "h2", "h3", "bullet", "ordered", "check",
        "quote", "divider", "code", "table", "image", "file", "link",
        "date", "meeting", "task", "status", "priority", "reminder",
    ):
        assert f'id: "{command}"' in script
    for field in ("status", "priority", "reminder_date"):
        assert f'focusWorkField("{field}")' in script


def test_vendored_editor_is_pinned_and_licensed():
    vendor = ROOT / "static" / "vendor" / "toastui-editor"
    assert (vendor / "toastui-editor.min.js").stat().st_size > 300_000
    assert (vendor / "toastui-editor.min.css").stat().st_size > 150_000
    assert (vendor / "ko-kr.js").stat().st_size > 5_000
    assert "MIT License" in (vendor / "LICENSE").read_text(encoding="utf-8")
    assets = _read("templates/_wysiwyg_editor_scripts.html")
    assert "toastui-editor.min.js" in assets
    assert "ko-kr.js" in assets
    assert "?v=3.2.2-all1" in assets


def test_task_lists_render_safely_in_board_and_tips_content():
    markdown = "- [ ] 확인 전\n- [x] 완료\n\n<script>alert(1)</script>"
    board_html = str(app_module._render_community_markdown(markdown))
    tip_html = tips_content.render_markdown(markdown)
    for rendered in (board_html, tip_html):
        assert 'class="task-list-item"' in rendered
        assert 'type="checkbox"' in rendered
        assert "checked" in rendered
        assert "disabled" in rendered
        assert "<script" not in rendered
