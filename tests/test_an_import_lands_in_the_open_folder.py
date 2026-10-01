# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B997` — a file imported from inside a folder lands in that folder.

Found by `P21-01`: the Library's import doors took no folder, so a file
imported while *Clients/Acme* was open landed in Unfiled, and `P21-01` switched
the view to Unfiled so the import did not seem to vanish. Every door now takes
the folder that is open:

  * `POST /api/document` (text, `.docx` and each spreadsheet sheet), and
    `POST /api/documents/import-pdf` / `import-office`, driven through the real
    routers with `TestClient` over a real upload store and a real SQLite file
    (the `P21-03` harness): the document is in the folder, the folder exists
    for its owner, a refused path is refused before the file is stored, and no
    folder still means Unfiled (`Law 1`);
  * `libraryImportFiles` in `static/js/documentLibrary.js`, cut out with
    `js_function` and run under node: every branch sends the folder;
  * the Import button's handler (`libraryImportPicked`), run the same way: it
    sends the open folder and leaves the view where it is.
"""

import pytest

import core.database as cdb
from tests.test_an_uploaded_document_keeps_its_name import env  # noqa: F401
from tests.test_attachment_extension_registers import _minimal_pdf, _odt_document
from tests.test_document_folders_js import _cut, _js, sandbox  # noqa: F401


def _row(env, doc_id):  # noqa: F811
    db = env.Session()
    try:
        d = db.query(cdb.Document).filter(cdb.Document.id == doc_id).one()
        return {"folder": d.folder, "owner": d.owner}
    finally:
        db.close()


def _folder_rows(env, owner="alice"):  # noqa: F811
    db = env.Session()
    try:
        return sorted(r.path for r in db.query(cdb.DocumentFolder)
                      .filter(cdb.DocumentFolder.owner == owner).all())
    finally:
        db.close()


def _uploads(env):  # noqa: F811
    return len(env.handler._load_upload_index())


IMPORTS = [
    ("import-pdf", "Board pack.pdf", _minimal_pdf("imported")),
    ("import-office", "Board pack.odt", _odt_document("imported prose")),
]


# ── the routes ──────────────────────────────────────────────────────────────

def test_a_text_import_lands_in_the_folder_that_was_open(env):  # noqa: F811
    r = env.client.post("/api/document", json={
        "source_name": "minutes.md", "content": "# Minutes", "folder": "Clients/Acme"})
    assert r.status_code == 200, r.text
    assert r.json()["folder"] == "Clients/Acme"
    assert _row(env, r.json()["id"])["folder"] == "Clients/Acme"
    # The folder and its parent exist as folders, not only as a document's
    # string, so they stay listed if the document moves on.
    assert _folder_rows(env) == ["Clients", "Clients/Acme"]
    listed = env.client.get("/api/documents/library", params={"folder": "Clients/Acme"})
    assert [d["id"] for d in listed.json()["documents"]] == [r.json()["id"]]


@pytest.mark.parametrize("route,name,body", IMPORTS, ids=["import-pdf", "import-office"])
def test_an_uploaded_import_lands_in_the_folder_that_was_open(env, route, name, body):  # noqa: F811
    r = env.client.post(f"/api/documents/{route}", data={"folder": "Clients/Acme"},
                        files={"file": (name, body, "application/octet-stream")})
    assert r.status_code == 200, r.text
    assert r.json()["folder"] == "Clients/Acme"
    assert _row(env, r.json()["id"]) == {"folder": "Clients/Acme", "owner": "alice"}
    assert _folder_rows(env) == ["Clients", "Clients/Acme"]


@pytest.mark.parametrize("route,name,body", IMPORTS, ids=["import-pdf", "import-office"])
def test_a_path_the_folders_refuse_is_refused_before_the_file_is_stored(env, route, name, body):  # noqa: F811
    before = _uploads(env)
    r = env.client.post(f"/api/documents/{route}", data={"folder": "Clients/../Secrets"},
                        files={"file": (name, body, "application/octet-stream")})
    assert r.status_code == 400, r.text
    assert _uploads(env) == before, "the upload was stored before the folder was read"
    db = env.Session()
    try:
        assert db.query(cdb.Document).count() == 0
    finally:
        db.close()


def test_a_text_import_with_a_refused_path_makes_nothing(env):  # noqa: F811
    r = env.client.post("/api/document", json={
        "source_name": "a.md", "content": "x", "folder": "Unfiled/inside"})
    assert r.status_code == 400 and "Unfiled" in r.json()["detail"], r.text
    db = env.Session()
    try:
        assert db.query(cdb.Document).count() == 0
    finally:
        db.close()


@pytest.mark.parametrize("folder", [None, "", "Unfiled"])
def test_no_open_folder_still_means_unfiled(env, folder):  # noqa: F811
    body = {"source_name": "a.md", "content": "x"}
    if folder is not None:
        body["folder"] = folder
    r = env.client.post("/api/document", json=body)
    assert r.status_code == 200, r.text
    assert _row(env, r.json()["id"])["folder"] is None and _folder_rows(env) == []
    pdf = env.client.post("/api/documents/import-pdf",
                          files={"file": ("p.pdf", _minimal_pdf("p"), "application/pdf")})
    assert pdf.status_code == 200 and _row(env, pdf.json()["id"])["folder"] is None


def test_the_folder_is_the_importer_s_own(env, monkeypatch):  # noqa: F811
    """Bob imports into "Clients" while Alice has a "Clients": he gets his own
    folder of that name, and hers holds what it held."""
    who = {"user": "alice"}
    monkeypatch.setattr("src.auth_helpers.require_privilege", lambda request, priv: who["user"])
    first = env.client.post("/api/document", json={"source_name": "a.md", "content": "a",
                                                   "folder": "Clients"})
    who["user"] = "bob"
    second = env.client.post("/api/document", json={"source_name": "b.md", "content": "b",
                                                    "folder": "Clients"})
    assert first.status_code == second.status_code == 200
    assert _row(env, second.json()["id"]) == {"folder": "Clients", "owner": "bob"}
    assert _folder_rows(env, "alice") == ["Clients"] and _folder_rows(env, "bob") == ["Clients"]


# ── the library under node ──────────────────────────────────────────────────

_IMPORT = """
    let API_BASE = '';
    const CONVERTED_TO = { '.docx': 'markdown' };
    const SERVER_EXTRACTED_EXTS = new Set(['.odt', '.doc', '.pptx', '.epub']);
    const documentLanguage = () => 'markdown';
    async function ensureXLSX() {}
    window.XLSX = { read: () => ({ SheetNames: ['Q1', 'Q2'], Sheets: { Q1: {}, Q2: {} } }),
                    utils: { sheet_to_csv: () => 'a,b' } };
    async function readFileContent(f) { return 'text of ' + f.name; }
    let fetched = 0;
    async function libraryFetch() { fetched++; }
    class FormData { constructor() { this.fields = {}; }
      append(k, v) { this.fields[k] = typeof v === 'string' ? v : '<file>'; } }
    const sent = [];
    globalThis.fetch = async (url, opts) => {
      sent.push({ url, form: opts.body instanceof FormData ? opts.body.fields : null,
                  json: typeof opts.body === 'string' ? JSON.parse(opts.body) : null });
      return { ok: true, status: 200, json: async () => ({}) };
    };
    const file = (name) => ({ name, arrayBuffer: async () => new ArrayBuffer(0) });
    const FILES = ['a.pdf', 'b.odt', 'c.md', 'd.xlsx'].map(file);
    __IMPORT__
"""


def _import_case(sandbox, tail):  # noqa: F811
    body = _cut("async function libraryImportFiles(",
                "async function libraryImportFiles(fileList, folder = null)")
    return _js(sandbox, _IMPORT.replace("__IMPORT__", body) + tail)


def test_every_library_import_door_sends_the_open_folder(sandbox):  # noqa: F811
    out = _import_case(sandbox, """
        await libraryImportFiles(FILES, 'Clients/Acme');
        console.log(JSON.stringify({ sent, errors, fetched }));
    """)
    assert out["errors"] == []
    urls = [s["url"] for s in out["sent"]]
    assert urls == ["/api/documents/import-pdf", "/api/documents/import-office",
                    "/api/document", "/api/document", "/api/document"]
    pdf, office, text, sheet1, sheet2 = out["sent"]
    assert pdf["form"] == {"file": "<file>", "folder": "Clients/Acme"}
    assert office["form"] == {"file": "<file>", "folder": "Clients/Acme"}
    for posted in (text, sheet1, sheet2):
        assert posted["json"]["folder"] == "Clients/Acme", posted
    assert [sheet1["json"]["title"], sheet2["json"]["title"]] == ["d - Q1", "d - Q2"]
    assert out["fetched"] == 1


def test_an_import_from_all_documents_sends_no_folder(sandbox):  # noqa: F811
    out = _import_case(sandbox, """
        await libraryImportFiles(FILES);
        console.log(JSON.stringify({ sent }));
    """)
    pdf, office, text, sheet1, _sheet2 = out["sent"]
    assert "folder" not in pdf["form"] and "folder" not in office["form"]
    assert text["json"]["folder"] is None and sheet1["json"]["folder"] is None


_PICKED = """
    let _libraryFolderView = F.VIEW_ALL;
    const importFolder = F.importFolder;
    const spinnerModule = { createWhirlpool: () => ({ element: new Node('span'), stop() {} }) };
    const calls = [];
    async function libraryImportFiles(files, folder) {
      calls.push({ names: files.map((f) => f.name), folder });
    }
    const button = new Node('button');
    button.innerHTML = 'Import';
    const picked = (names) => ({ files: names.map((name) => ({ name })), value: 'x' });
    __PICKED__
"""


def test_the_import_button_files_into_the_open_folder_and_stays_there(sandbox):  # noqa: F811
    body = _cut("async function libraryImportPicked(",
                "async function libraryImportPicked(fileInput, importFileBtn)")
    out = _js(sandbox, _PICKED.replace("__PICKED__", body) + """
        _libraryFolderView = F.folderView('Clients/Acme');
        const input = picked(['a.pdf', 'b.md']);
        await libraryImportPicked(input, button);
        const stayed = _libraryFolderView;
        _libraryFolderView = F.VIEW_UNFILED;
        await libraryImportPicked(picked(['c.md']), button);
        _libraryFolderView = F.VIEW_ALL;
        await libraryImportPicked(picked(['d.md']), button);
        await libraryImportPicked(picked([]), button);
        console.log(JSON.stringify({ calls, stayed, cleared: input.value,
                                     label: button.innerHTML, disabled: button.disabled }));
    """)
    assert out["calls"] == [
        {"names": ["a.pdf", "b.md"], "folder": "Clients/Acme"},
        {"names": ["c.md"], "folder": None},
        {"names": ["d.md"], "folder": None},
    ]
    assert out["stayed"] == {"kind": "folder", "path": "Clients/Acme"}, "the view left the folder"
    assert out["cleared"] == "" and out["label"] == "Import" and out["disabled"] is False


def test_the_folder_an_import_goes_to_is_the_open_one_and_only_that(sandbox):  # noqa: F811
    out = _js(sandbox, """
        console.log(JSON.stringify([
          F.importFolder(F.folderView('Clients/Acme')), F.importFolder(F.VIEW_ALL),
          F.importFolder(F.VIEW_UNFILED), F.importFolder(null),
        ]));
    """)
    assert out == ["Clients/Acme", None, None, None]

