"""FM broadcast station identity and now-playing metadata helpers."""

from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path


_METADATA_TTL_S = 25.0
_metadata_cache: dict[str, tuple[float, dict]] = {}


STREAM_URLS = {
    # KUTX publishes these stream URLs at https://kutx.org/streams/.
    "kutx-989": "https://streams.kut.org/4428_192.mp3?aw_0_1st.playerid=tricore",
}

COMPOSER_NOW_URLS = {
    # NPR Composer widget for KUTX now-playing.
    "kutx-989": "https://api.composer.nprstations.org/v1/widget/50ef24ebe1c8a1369593d032/now?format=json",
}

IHEART_PAGES = {
    "kase-1007": "https://kase1007.iheart.com/",
    "kpez-1023": "https://thebeatatx.iheart.com/",
    "kvet-981": "https://981kvet.iheart.com/",
}


def _callsign_from_name(name: str) -> str:
    return name.split()[0].strip().upper()


def load_fm_stations(frequency_file: Path, include_now_playing: bool = True) -> list[dict]:
    data = json.loads(frequency_file.read_text(encoding="utf-8"))
    stations: list[dict] = []

    for channel in data.get("channels", []):
        if channel.get("service_type") != "fm_radio":
            continue

        frequency_hz = int(channel["frequency_hz"])
        callsign = channel.get("callsign") or _callsign_from_name(channel["name"])
        station = {
            "id": channel["id"],
            "callsign": callsign,
            "name": channel["name"],
            "system": channel["system"],
            "frequency_hz": frequency_hz,
            "frequency_mhz": round(frequency_hz / 1_000_000, 4),
            "favorite": bool(channel.get("favorite", False)),
            "station_id_source": "configured_station_list",
            "stream_url": channel.get("stream_url") or STREAM_URLS.get(channel["id"]),
            "composer_now_url": channel.get("composer_now_url") or COMPOSER_NOW_URLS.get(channel["id"]),
            "iheart_page_url": channel.get("iheart_page_url") or IHEART_PAGES.get(channel["id"]),
            "rds_program_service": channel.get("rds_program_service"),
            "rds_radio_text": channel.get("rds_radio_text"),
            "rds_status": "not_decoded",
            "now_playing": None,
            "song_title": None,
            "artist": None,
            "album": None,
            "metadata_source": None,
            "metadata_status": "not_configured",
        }

        if include_now_playing:
            station.update(fetch_now_playing(station))

        stations.append(station)

    return stations


def fetch_now_playing(station: dict) -> dict:
    stream_url = station.get("stream_url")
    composer_now_url = station.get("composer_now_url")
    iheart_page_url = station.get("iheart_page_url")
    if not stream_url and not composer_now_url and not iheart_page_url:
        return {
            "now_playing": None,
            "song_title": None,
            "artist": None,
            "album": None,
            "metadata_source": None,
            "metadata_status": "not_configured",
        }

    station_id = station["id"]
    cached = _metadata_cache.get(station_id)
    now = time.monotonic()
    if cached and now - cached[0] < _METADATA_TTL_S:
        return cached[1]

    metadata = _fetch_composer_now(composer_now_url) if composer_now_url else None
    if (not metadata or metadata.get("metadata_status") != "ok") and iheart_page_url:
        metadata = _fetch_iheart_recent(iheart_page_url)
    if not metadata or metadata.get("metadata_status") != "ok":
        metadata = _fetch_icy_metadata(stream_url) if stream_url else metadata
    _metadata_cache[station_id] = (now, metadata)
    return metadata


def _fetch_composer_now(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "TriCore Scanner/0.2"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8", errors="ignore"))
    except Exception as exc:
        return _metadata_result(status=f"metadata_error: {exc}", source="npr_composer")

    on_now = data.get("onNow") or {}
    song = on_now.get("song") or {}
    program = on_now.get("program") or {}
    artist = song.get("artistName")
    title = song.get("trackName")
    album = song.get("collectionName")
    show = program.get("name")
    hosts = ", ".join(host.get("name", "") for host in program.get("hosts", []) if host.get("name"))

    if not artist and not title and not show:
        return _metadata_result(status="metadata_empty", source="npr_composer")

    now_playing = " - ".join(part for part in [artist, title] if part) or show
    result = _metadata_result(
        status="ok",
        source="npr_composer",
        raw=json.dumps({"show": show, "host": hosts, "artist": artist, "title": title, "album": album}),
        now_playing=now_playing,
        artist=artist,
        song_title=title,
        album=album,
    )
    result["program_name"] = show
    result["program_host"] = hosts or None
    return result


def _fetch_iheart_recent(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 TriCore Scanner/0.2"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            text = response.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        return _metadata_result(status=f"metadata_error: {exc}", source="iheart_recent")

    index = text.find("component-track-list")
    if index < 0:
        return _metadata_result(status="metadata_empty", source="iheart_recent")

    fragment = text[index:index + 7000]
    item_match = re.search(r'<figure class="component-track-display type-recentlyplayed">(.*?)</figure>', fragment, re.S)
    if not item_match:
        return _metadata_result(status="metadata_empty", source="iheart_recent")

    parts = [
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", part)).strip()
        for part in re.findall(r'<[^>]*class="[^"]*(?:track-title|artist-name|collection-name|start-time)[^"]*"[^>]*>(.*?)</[^>]+>', item_match.group(1), re.S)
    ]
    if len(parts) < 2:
        collapsed = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", item_match.group(1))).strip()
        return _metadata_result(status="metadata_unparsed", source="iheart_recent", raw=collapsed)

    title = parts[0] or None
    artist = parts[1] if len(parts) > 1 else None
    album = parts[2] if len(parts) > 2 else None
    played_at = parts[3] if len(parts) > 3 else None
    now_playing = " - ".join(part for part in [artist, title] if part)
    result = _metadata_result(
        status="ok",
        source="iheart_recent",
        raw=json.dumps({"artist": artist, "title": title, "album": album, "played_at": played_at}),
        now_playing=now_playing,
        artist=artist,
        song_title=title,
        album=album,
    )
    result["played_at"] = played_at
    return result


def _fetch_icy_metadata(stream_url: str) -> dict:
    request = urllib.request.Request(
        stream_url,
        headers={
            "Icy-MetaData": "1",
            "User-Agent": "TriCore Scanner/0.2",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            metaint = response.headers.get("icy-metaint")
            if not metaint:
                return _metadata_result(status="stream_has_no_icy_metadata", source="stream")

            interval = int(metaint)
            response.read(interval)
            length_byte = response.read(1)
            if not length_byte:
                return _metadata_result(status="metadata_empty", source="stream")

            metadata_length = length_byte[0] * 16
            raw = response.read(metadata_length).decode("utf-8", errors="ignore").strip("\x00").strip()
    except Exception as exc:
        return _metadata_result(status=f"metadata_error: {exc}", source="stream")

    if not raw:
        return _metadata_result(status="metadata_empty", source="stream")

    title = _extract_stream_title(raw)
    if not title:
        return _metadata_result(status="metadata_unparsed", source="stream", raw=raw)

    artist, song_title = _split_artist_title(title)
    return _metadata_result(
        status="ok",
        source="icy_stream",
        raw=raw,
        now_playing=title,
        artist=artist,
        song_title=song_title,
    )


def _extract_stream_title(raw: str) -> str | None:
    match = re.search(r"StreamTitle='([^']*)'", raw)
    if match:
        value = match.group(1).strip()
        return _clean_stream_title(value) or None
    return raw.strip() or None


def _clean_stream_title(value: str) -> str:
    value = value.strip()
    text_match = re.search(r'text="([^"]+)"', value)
    if text_match:
        title = text_match.group(1).strip()
        artist = value.split(" - ", 1)[0].strip()
        if artist and not artist.startswith("-") and "text=" not in artist:
            return f"{artist} - {title}"
        return title
    return value


def _split_artist_title(value: str) -> tuple[str | None, str | None]:
    cleaned = re.sub(r"\s+", " ", value).strip()
    for separator in (" - ", " – ", " — "):
        if separator in cleaned:
            artist, title = cleaned.split(separator, 1)
            return artist.strip() or None, title.strip() or None
    return None, cleaned or None


def _metadata_result(
    status: str,
    source: str | None,
    raw: str | None = None,
    now_playing: str | None = None,
    artist: str | None = None,
    song_title: str | None = None,
    album: str | None = None,
) -> dict:
    return {
        "now_playing": now_playing,
        "song_title": song_title,
        "artist": artist,
        "album": album,
        "metadata_source": source,
        "metadata_status": status,
        "metadata_raw": raw,
        "metadata_checked_at": time.time(),
    }
