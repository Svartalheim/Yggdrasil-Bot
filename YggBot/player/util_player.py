from yarl import URL


class UtilTrackPlayer:
	@staticmethod
	def extract_index_youtube(q: str) -> int:
		index: int = 0

		if q.startswith("http"):
			url = URL(q)
			# TODO Temp fix YT
			try:
				index = int(url.query.get("start_radio")) or int(url.query.get("index"))
			except (ValueError, TypeError):
				index = None

		return index

	@staticmethod
	def parse_sec(sec: int, show_suffix: bool = True) -> str:
		sec = sec // 1000
		m, s = divmod(sec, 60)
		h, m = divmod(m, 60)
		d, _ = divmod(h, 24)

		if sec >= 86400:
			return (
				f"{d}d {h}h {m:02d}m {s:02d}s"
				if show_suffix
				else f"{d}:{h:02d}:{m:02d}:{s:02d}"
			)
		elif sec >= 3600:
			return (
				f"{h}h {m:02d}m {s:02d}s" if show_suffix else f"{h:02d}:{m:02d}:{s:02d}"
			)
		elif sec >= 60:
			return f"{m}m {s:02d}s" if show_suffix else f"{m:02d}:{s:02d}"
		else:
			return f"{s}s" if show_suffix else f"{s:02d}"
