from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_shared_file_upload_ui_preserves_native_inputs_and_form_contracts():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "js" / "file-upload.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "site-components.css").read_text(encoding="utf-8")

    assert "js/file-upload.js" in base
    assert 'root.querySelectorAll?.(\'input[type="file"]\')' in script
    assert 'input.dataset.fileUiReady = "true"' in script
    assert 'input.addEventListener("change"' in script
    assert 'input.files' in script
    assert "선택된 파일 없음" in script
    assert 'button.className = "btn btn-outline file-upload-button"' in script
    assert 'button.dataset.uiIcon = "upload"' in script
    assert 'input.closest(".markdown-image-button")' in script
    assert ".file-upload-input:focus-visible + .file-upload-display" in css
    assert "width: auto !important" in css
    assert "max-width: 55%" in css
    assert "text-overflow: ellipsis" in css
    assert "min-width: 0" in css


def test_upload_templates_keep_names_accept_rules_and_validation_attributes():
    expected = {
        "account.html": ('name="picture"', "required"),
        "disclosures.html": ('name="document"', 'accept="application/pdf,.pdf"', "required"),
        "library.html": ('name="document"', 'accept="application/pdf,.pdf"', "required"),
        "official_docs/form.html": ('name="attachments"', "multiple", "required"),
        "official_docs/import_excel.html": ('name="ledger"', "required"),
        "tips/form.html": ('name="attachments"', "multiple"),
        "work_notes/form.html": ('name="attachments"', "multiple"),
    }

    for filename, markers in expected.items():
        template = (ROOT / "templates" / filename).read_text(encoding="utf-8")
        assert 'type="file"' in template
        for marker in markers:
            assert marker in template
