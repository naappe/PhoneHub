from pathlib import Path


def test_downloaded_viewer_works_from_file_url():
    index = Path('viewer/index.html').read_text(encoding='utf-8')
    app = Path('viewer/app.js').read_text(encoding='utf-8')

    assert 'type="module"' not in index, 'Downloaded viewer must not require a local ES module load from file://'
    assert 'cdn.jsdelivr.net/npm/@supabase/supabase-js@2' in index, 'Supabase browser bundle must be loaded as a classic script'
    assert 'import { createClient }' not in app, 'app.js must not use ESM import when opened directly from disk'
