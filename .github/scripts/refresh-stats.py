#!/usr/bin/env python3
"""Refresh public stats for the Handy Little Hacks channel -> stats.json (project root).
Uses yt-dlp (pip install --user yt-dlp). Lists the channel's /shorts and /videos tabs,
then reads each video's public view_count / like_count. Shares are NOT public:
fill "sharesManual" in stats.json by hand from YouTube Studio (it is preserved on refresh).
Then run:  node build/build.js   to bake the numbers into index.html + index-cdn.html.

Also used by the GitHub Action (.github/workflows/refresh-stats.yml) in the deploy repo.
Env: STATS_OUT=path overrides the output file. Fallback when yt-dlp is blocked: the channel's
public RSS feed (views only; its starRating count is NOT the real like count, so likes stay null).
If nothing at all can be fetched, the previous file is left untouched and the script exits 1."""
import json, os, shutil, subprocess, sys, datetime, urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

CHANNEL = 'https://www.youtube.com/@HandyLittleHacks'
CHANNEL_ID = 'UCJnEHmsTXfSJw6abv5bnhwA'
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT = os.environ.get('STATS_OUT') or os.path.join(ROOT, 'stats.json')
YTDLP = [sys.executable, '-m', 'yt_dlp'] + (['--js-runtimes', 'node'] if shutil.which('node') else [])
RSS = f'https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}'

def run(args):
    r = subprocess.run(YTDLP + args, capture_output=True, text=True, timeout=180)
    return r.returncode, r.stdout, r.stderr

def list_tab(tab):
    code, out, err = run(['--flat-playlist', '-J', f'{CHANNEL}/{tab}'])
    if code != 0 or not out.strip() or out.strip() == 'null':
        print(f'  {tab}: none ({err.strip().splitlines()[-1] if err.strip() else "no output"})')
        return []
    ids = [e['id'] for e in (json.loads(out).get('entries') or []) if e and e.get('id')]
    print(f'  {tab}: {len(ids)} found')
    return ids

def video_meta(vid):
    code, out, err = run(['--skip-download', '-j', '--', f'https://www.youtube.com/watch?v={vid}'])
    if code != 0 or not out.strip():
        print(f'  {vid}: metadata failed'); return {'id': vid, 'views': None, 'likes': None}
    d = json.loads(out)
    if d.get('channel_id') and d['channel_id'] != CHANNEL_ID:
        return None
    return {'id': vid, 'title': d.get('title'), 'uploadDate': d.get('upload_date'),
            'views': d.get('view_count'), 'likes': d.get('like_count')}

def rss_videos():
    """Public RSS feed: last ~15 uploads, media:statistics views. Likes left null on purpose."""
    try:
        req = urllib.request.Request(RSS, headers={'User-Agent': 'Mozilla/5.0'})
        root = ET.fromstring(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        print(f'  rss: failed ({e})'); return []
    ns = {'a': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015', 'm': 'http://search.yahoo.com/mrss/'}
    out = []
    for e in root.findall('a:entry', ns):
        st = e.find('m:group/m:community/m:statistics', ns)
        v = st.get('views') if st is not None else None
        out.append({'id': e.find('yt:videoId', ns).text, 'title': e.find('a:title', ns).text,
                    'uploadDate': (e.find('a:published', ns).text or '')[:10].replace('-', ''),
                    'views': int(v) if v not in (None, '') else None, 'likes': None})
    print(f'  rss: {len(out)} found'); return out

def main():
    prev = {}
    if os.path.exists(OUT):
        try: prev = json.load(open(OUT))
        except Exception: prev = {}
    print('Listing channel videos…')
    ids = []
    for tab in ('shorts', 'videos'):
        for v in list_tab(tab):
            if v not in ids: ids.append(v)
    vids = [m for m in (video_meta(v) for v in ids) if m]
    method = 'yt-dlp: --flat-playlist on /shorts + /videos, then per-video metadata'
    if not vids or all(m['views'] is None for m in vids):
        print('yt-dlp got nothing usable, trying public RSS feed…')
        vids = rss_videos(); ids = [m['id'] for m in vids]
        method = 'YouTube public RSS feed (views only; likes not available there)'
    if not vids or all(m['views'] is None for m in vids):
        print('ERROR: could not fetch any public counts; keeping previous stats.json unchanged')
        sys.exit(1)
    for m in vids: print(f"  {m['id']}: views={m['views']} likes={m['likes']}  {m.get('title') or ''}")
    def total(key):
        known = [m[key] for m in vids if m[key] is not None]
        return (sum(known) if known else None), len(vids) - len(known)
    tv, vmiss = total('views'); tl, lmiss = total('likes')
    now = datetime.datetime.now(ZoneInfo('America/Chicago'))
    utc = datetime.datetime.now(datetime.timezone.utc)
    stats = {
        'channel': 'HANDY LITTLE HACKS', 'handle': '@HandyLittleHacks', 'url': CHANNEL, 'channelId': CHANNEL_ID,
        'videoCount': len(vids) if ids else None,
        'totalViews': tv if ids else None, 'viewsMissing': vmiss,
        'totalLikes': tl if ids else None, 'likesMissing': lmiss,
        'sharesManual': prev.get('sharesManual'),  # fill in from YouTube Studio; null shows as —
        'updated': now.isoformat(timespec='seconds'),
        'updatedCT': now.strftime('%b %-d, %Y %-I:%M %p') + ' CT',
        'fetchedAt': utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'fetchedBy': os.environ.get('STATS_FETCHED_BY', 'box'),
        'method': method,
        'videos': vids,
    }
    json.dump(stats, open(OUT, 'w'), indent=2)
    print(f"\nVideos {stats['videoCount']} · Views {tv} · Likes {tl} (missing likes on {lmiss}) · Shares {stats['sharesManual']}")
    print('Wrote', os.path.abspath(OUT), '— now run: node build/build.js')

if __name__ == '__main__':
    main()
