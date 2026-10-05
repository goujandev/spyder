"""Source capabilities and yt-dlp options, without network or ffmpeg."""
import unittest
from unittest.mock import Mock, patch
from spyder import downloader as d, platforms


class DownloadOptionsTests(unittest.TestCase):
    def test_source_capabilities(self):
        for video, audio, count in ((True, True, 4), (False, True, 3), (True, False, 1)):
            with self.subTest(video=video, audio=audio):
                presets = d.build_presets({"formats": [{"vcodec": "h264" if video else "none",
                    "acodec": "aac" if audio else "none"}]})
                self.assertEqual(len(presets), count)
                self.assertEqual(any(not p.audio_only for p in presets), video)
                self.assertEqual([p.audio_codec for p in presets if p.audio_only],
                                 ["mp3", "m4a", "wav"] if audio else [])
                if not audio:
                    self.assertEqual(presets[0].format_selector, "bv*")
        with self.assertRaises(d.SpyderError):
            d.build_presets({"formats": []})
        self.assertEqual(len(d.build_presets({"url": "https://example.com/a", "acodec": "aac"})), 3)

    def test_tiktok_filter_and_video_ladder(self):
        formats = [{"height": h, "width": 1920, "vcodec": "h264", "acodec": "aac",
                    "format_note": note} for h, note in ((1080, "watermark"), (720, ""), (480, ""))]
        presets = d.build_presets({"formats": formats}, platforms.TIKTOK)
        self.assertEqual([p.label for p in presets if not p.audio_only],
                         [platforms.TIKTOK.best_label, "720p (HD)", "480p"])
        self.assertTrue(all(d.NO_WATERMARK in p.format_selector for p in presets))
        with self.assertRaises(d.SpyderError):
            d.build_presets({"formats": formats[:1]}, platforms.TIKTOK)

    def run_download(self, preset, result):
        logs = []
        captured = {}
        def make_ydl(options):
            captured.update(options)
            client = Mock()
            def extract(*args, **kwargs):
                options["progress_hooks"][0]({"status": "finished", "filename": "source.webm"})
                hook = options["postprocessor_hooks"][0]
                name = "ExtractAudio" if preset.audio_only else "Merger"
                final = "final." + (preset.audio_codec if preset.audio_only else "mp4")
                for _ in range(2):
                    hook({"status": "started", "postprocessor": name})
                hook({"status": "finished", "postprocessor": name, "info_dict": {"filepath": final}})
                return result
            client.extract_info.side_effect = extract
            client.__enter__ = Mock(return_value=client)
            client.__exit__ = Mock(return_value=False)
            return client
        with patch.object(d, "find_ffmpeg", return_value="ffmpeg"), patch.object(d, "SingleVideoYoutubeDL", side_effect=make_ydl):
            path = d.download("https://example.com/media", preset, "out", Mock(), logs.append, lambda: False)
        return captured, logs, path

    def test_each_audio_codec_and_final_path(self):
        for codec, quality in (("mp3", "320"), ("m4a", "256"), ("wav", None)):
            with self.subTest(codec=codec):
                preset = d.Preset(codec, "ba/b", True, codec)
                opts, logs, path = self.run_download(preset, {"requested_downloads": [{"filepath": "source.webm"}]})
                self.assertEqual(path, "final." + codec)
                self.assertEqual(opts["format"], "ba/b")
                pp = opts["postprocessors"][0]
                self.assertEqual(pp["key"], "FFmpegExtractAudio")
                self.assertEqual(pp["preferredcodec"], codec)
                self.assertEqual(pp.get("preferredquality"), quality)
                self.assertNotIn("merge_output_format", opts)
                self.assertEqual(logs, [f"preparing {codec.upper()} audio (converting if needed)"])

    def test_video_and_moved_final_path(self):
        preset = d.Preset("Best", d._selector(platforms.GENERIC))
        opts, logs, path = self.run_download(preset, {"filepath": "moved/video.mkv"})
        self.assertEqual(path, "moved/video.mkv")
        self.assertEqual(opts["format"], "bv*+ba/b")
        self.assertEqual(opts["merge_output_format"], "mp4")
        self.assertNotIn("postprocessors", opts)
        self.assertEqual(logs, ["merging video and audio"])

    def test_cancellation(self):
        with patch.object(d, "find_ffmpeg", return_value="ffmpeg"), patch.object(d, "SingleVideoYoutubeDL") as ydl:
            ydl.return_value.__enter__.return_value.extract_info.side_effect = d.DownloadCancelled()
            with self.assertRaises(d.DownloadCancelled):
                d.download("url", d.Preset("MP3", "ba/b", True), "out", Mock(), Mock(), lambda: True)
