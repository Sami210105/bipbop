/* Thin wrappers around the serve.py JSON API. */

export async function fetchSongs() {
  const r = await fetch("/api/songs");
  if (!r.ok) throw new Error("songs request failed");
  return r.json(); // { songs: [...], llm: {...} }
}

export async function fetchLesson(title, refresh = false) {
  const url = `/api/lesson?title=${encodeURIComponent(title)}${refresh ? "&refresh=1" : ""}`;
  const r = await fetch(url);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `lookup failed (${r.status})`);
  return data.lesson;
}
