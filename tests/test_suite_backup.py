import io,json,sqlite3,zipfile
from pathlib import Path
import pytest
from ifms_suite.backups import create_bundle,validate_bundle

def test_backup_contains_database_and_original_documents(tmp_path):
    db=tmp_path/'data.db';c=sqlite3.connect(db);c.execute('CREATE TABLE example(value TEXT)');c.execute("INSERT INTO example VALUES('kept')");c.commit();c.close()
    uploads=tmp_path/'uploads';(uploads/'suite').mkdir(parents=True);(uploads/'suite'/'source.pdf').write_bytes(b'%PDF-test')
    bundle=create_bundle(db,uploads)
    with zipfile.ZipFile(bundle) as z:
        assert 'database.sqlite' in z.namelist()
        assert z.read('sources/suite/source.pdf')==b'%PDF-test'
    validate_bundle(bundle.getvalue())

def test_backup_rejects_unsafe_paths(tmp_path):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('../escape','bad');z.writestr('manifest.json','{}')
    with pytest.raises(ValueError):validate_bundle(b.getvalue())

def test_backup_restores_excel_original_and_creates_pre_restore_snapshot(tmp_path):
    from ifms_suite.backups import apply_pending
    db=tmp_path/'ifms_data.db';c=sqlite3.connect(db);c.execute('CREATE TABLE example(value TEXT)');c.execute("INSERT INTO example VALUES('original')");c.commit();c.close()
    uploads=tmp_path/'uploads';(uploads/'suite').mkdir(parents=True);(uploads/'suite'/'statement.xlsx').write_bytes(b'PK-source')
    bundle=create_bundle(db,uploads)
    with zipfile.ZipFile(bundle) as z:assert z.read('sources/suite/statement.xlsx')==b'PK-source'
    c=sqlite3.connect(db);c.execute("UPDATE example SET value='changed'");c.commit();c.close()
    (tmp_path/'pending-restore.zip').write_bytes(bundle.getvalue());apply_pending(tmp_path)
    c=sqlite3.connect(db)
    try:assert c.execute('SELECT value FROM example').fetchone()[0]=='original'
    finally:c.close()
    assert list((tmp_path/'backups').glob('before-restore-*.zip'))
    assert not (tmp_path/'pending-restore.zip').exists()
