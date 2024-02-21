from yarl import URL


class UtilTrackPlayer:

    @staticmethod
    def extract_index_youtube(q: str) -> int:
        index: int = 0

        if q.startswith('http'):
            url = URL(q)
            # TODO Temp fix YT
            try:
                index = int(url.query.get('start_radio')) or int(
                    url.query.get('index'))
            except (ValueError, TypeError):
                index = None

        return index

    @staticmethod
    def parse_sec(sec: int) -> str:
        sec = sec // 1000
        m, s = divmod(sec, 60)
        h, m = divmod(m, 60)
        if sec >= 3600:
            return f'{h:d}h {m:02d}m {s:02d}s'
        else:
            return f'{m:02d}m {s:02d}s'
