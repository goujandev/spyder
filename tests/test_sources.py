"""Offline source fixtures; real yt-dlp routing, normalization and selectors."""
import copy
import unittest
from unittest.mock import Mock, patch

import yt_dlp
from yt_dlp.extractor.generic import GenericIE
from yt_dlp.extractor.pinterest import PinterestIE, PinterestCollectionIE
from yt_dlp.extractor.reddit import RedditIE

from spyder import downloader as d, platforms as p

PIN_URL = "https://www.pinterest.com/pin/664281013778109217/"
REDDIT_URL = "https://www.reddit.com/r/videos/comments/6rrwyj/that_small_heart_attack/"
PIN_DATA = {
    "id": "664281013778109217", "title": "Origami", "domain": "uploaded by user",
    "videos": {"video_list": {
        "V_720P": {"url": "https://v.pinimg.com/videos/720p/pin.mp4",
                   "width": 1280, "height": 720, "duration": 57700},
        "V_360P": {"url": "https://v.pinimg.com/videos/360p/pin.mp4",
                   "width": 640, "height": 360, "duration": 57700},
    }},
}
REDDIT_INFO = {
    "id": "zv89llsvexdz", "title": "That small heart attack.", "duration": 12,
    "uploader": "Antw87", "formats": [
        {"format_id": "dash-480", "url": "https://v.redd.it/zv89llsvexdz/DASH_480.mp4",
         "width": 854, "height": 480, "vcodec": "avc1.4d401e", "acodec": "none"},
        {"format_id": "dash-720", "url": "https://v.redd.it/zv89llsvexdz/DASH_720.mp4",
         "width": 1280, "height": 720, "vcodec": "avc1.4d401f", "acodec": "none"},
        {"format_id": "dash-audio", "url": "https://v.redd.it/zv89llsvexdz/DASH_AUDIO_128.mp4",
         "vcodec": "none", "acodec": "mp4a.40.2", "abr": 128},
    ],
}


class PlatformTests(unittest.TestCase):
    def test_regional_and_short_hosts(self):
        for host in p.PINTEREST_DOMAINS:
            with self.subTest(host=host):
                url = "https://www." + host + "/pin/664281013778109217/"
                self.assertIs(p.detect(url), p.PINTEREST)
                self.assertTrue(PinterestIE.suitable(url))
        for host, platform in (("pin.it", p.PINTEREST), ("co.pinterest.com", p.PINTEREST),
                               ("reddit.com", p.REDDIT), ("old.reddit.com", p.REDDIT),
                               ("redd.it", p.REDDIT), ("v.redd.it", p.REDDIT)):
            self.assertIs(p.detect("https://" + host.upper() + "/example"), platform)
        self.assertFalse(PinterestIE.suitable("https://pin.it/example"))
        self.assertTrue(GenericIE.suitable("https://pin.it/example"))

    def test_lookalikes_are_not_recognised(self):
        for host in ("pinterest.com.evil.test", "reddit.com.evil.test", "pin.it.evil.test",
                     "redd.it.evil.test", "notpinterest.com", "notreddit.com", "pinterest.xyz",
                     "pinterest.co.uk.evil.test", "pinterestcom", "pinterest.com@evil.test"):
            with self.subTest(host=host):
                self.assertIs(p.detect("https://" + host + "/pin/123"), p.GENERIC)
        self.assertIs(p.detect("https://evil.test/?url=https://pinterest.com/pin/123"), p.GENERIC)

    def test_extractor_names(self):
        for name in ("Pinterest", "pinterest", "PinterestCollection"):
            self.assertIs(p.from_extractor(name), p.PINTEREST)
        self.assertIs(p.from_extractor("Reddit"), p.REDDIT)
        self.assertIs(p.from_extractor("TikTok"), p.TIKTOK)
        self.assertIs(p.from_extractor(""), p.GENERIC)


class SourcePipelineTests(unittest.TestCase):
    def setUp(self):
        # Any unexpected network request is a fixture failure, not a live test.
        self.network = patch.object(yt_dlp.YoutubeDL, "urlopen", side_effect=AssertionError("Unexpected network"))
        self.network.start()
        self.addCleanup(self.network.stop)
        initialization = patch.object(RedditIE, "_real_initialize")
        initialization.start()
        self.addCleanup(initialization.stop)

    def normalized(self, info):
        with d.SingleVideoYoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            return ydl.process_ie_result(copy.deepcopy(info), download=False)

    def selected(self, info, preset):
        with d.SingleVideoYoutubeDL({"quiet": True, "no_warnings": True,
                                    "format": preset.format_selector}) as ydl:
            return ydl.process_ie_result(copy.deepcopy(info), download=False)

    def test_pinterest_unknown_codecs_and_download_requests(self):
        raw = PinterestIE()._extract_video(copy.deepcopy(PIN_DATA))
        normalized = self.normalized(raw)
        self.assertTrue(all(f.get("vcodec") is None and f.get("acodec") is None
                            for f in normalized["formats"]))
        with patch.object(PinterestIE, "_call_api", return_value={"data": PIN_DATA}):
            info = d.probe(PIN_URL)
        self.assertIs(info.platform, p.PINTEREST)
        self.assertEqual(info.duration, "0:57")
        self.assertEqual([x.label for x in info.presets], [p.PINTEREST.best_label, "720p (HD)", "360p"])
        for preset, height in zip(info.presets, (720, 720, 360)):
            self.assertFalse(preset.audio_only)
            self.assertEqual(self.selected(raw, preset)["height"], height)
            with patch.object(d, "find_ffmpeg", return_value="ffmpeg"), patch.object(d, "SingleVideoYoutubeDL") as client:
                client.return_value.__enter__.return_value.extract_info.return_value = {"filepath": "pin.mp4"}
                self.assertEqual(d.download(PIN_URL, preset, "out", Mock(), Mock(), lambda: False), "pin.mp4")
                options = client.call_args.args[0]
                self.assertEqual(options["format"], preset.format_selector)
                self.assertTrue(options["noplaylist"])
                self.assertNotIn("postprocessors", options)
                client.return_value.__enter__.return_value.extract_info.assert_called_once_with(PIN_URL, download=True)

    def test_reddit_split_stream_selection(self):
        with patch.object(RedditIE, "_real_extract", side_effect=lambda url: copy.deepcopy(REDDIT_INFO)):
            info = d.probe(REDDIT_URL)
        self.assertIs(info.platform, p.REDDIT)
        self.assertEqual(info.uploader, "Antw87")
        self.assertEqual([x.audio_codec for x in info.presets if x.audio_only], ["mp3", "m4a", "wav"])
        for preset in info.presets:
            selected = self.selected(REDDIT_INFO, preset)
            if preset.audio_only:
                self.assertEqual(selected["format_id"], "dash-audio")
            else:
                self.assertEqual(len(selected["requested_formats"]), 2)
                self.assertEqual(selected["requested_formats"][1]["format_id"], "dash-audio")
                if preset.label.startswith("480"):
                    self.assertEqual(selected["height"], 480)

    def test_reddit_download_passes_selected_streams_to_downloader(self):
        with patch.object(RedditIE, "_real_extract", side_effect=lambda url: copy.deepcopy(REDDIT_INFO)):
            info = d.probe(REDDIT_URL)
            for preset in info.presets:
                with patch.object(d, "find_ffmpeg", return_value="ffmpeg"), patch.object(yt_dlp.YoutubeDL, "process_info") as process:
                    d.download(REDDIT_URL, preset, "out", Mock(), Mock(), lambda: False)
                    selected = process.call_args.args[0]
                    if preset.audio_only:
                        self.assertEqual(selected["format_id"], "dash-audio")
                    else:
                        self.assertEqual(selected["requested_formats"][1]["format_id"], "dash-audio")

    def test_shortlinks_route_through_generic_redirect(self):
        for short, target, extractor, result in (
            ("https://pin.it/example", PIN_URL, PinterestIE, PinterestIE()._extract_video(PIN_DATA)),
            ("https://redd.it/6rrwyj", REDDIT_URL, RedditIE, REDDIT_INFO),
        ):
            with self.subTest(short=short), patch.object(GenericIE, "_request_webpage", return_value=Mock(url=target)) as request, patch.object(extractor, "_real_extract", return_value=copy.deepcopy(result)) as extract:
                info = d.probe(short)
                self.assertTrue(info.presets)
                self.assertIs(info.platform, p.detect(target))
                self.assertEqual(request.call_args.args[0], short)
                extract.assert_called_once_with(target)

    def test_collections_rejected_before_entries_for_probe_and_download(self):
        def entries():
            self.fail("Collection entries must not be visited")
            yield REDDIT_INFO
        for kind in ("playlist", "multi_video", "compat_list"):
            for downloading in (False, True):
                with self.subTest(kind=kind, downloading=downloading), d.SingleVideoYoutubeDL({"quiet": True}) as ydl:
                    with self.assertRaisesRegex(d.SpyderError, "single video"):
                        ydl.process_ie_result({"_type": kind, "id": "collection", "entries": entries()}, download=downloading)
        with patch.object(PinterestCollectionIE, "_real_extract", return_value={"_type": "playlist", "entries": entries()}):
            with self.assertRaisesRegex(d.SpyderError, "Boards, galleries"):
                d.probe("https://www.pinterest.com/example/board/")
            with patch.object(d, "find_ffmpeg", return_value="ffmpeg"), self.assertRaisesRegex(d.SpyderError, "Boards, galleries"):
                d.download("https://www.pinterest.com/example/board/", d.Preset("Best", "bv*"), "out", Mock(), Mock(), lambda: False)

    def test_photos_empty_and_story_galleries(self):
        photo = {"id": "123", "title": "Photo", "images": {"orig": {"url": "https://i.pinimg.com/photo.jpg"}}}
        with patch.object(PinterestIE, "_call_api", return_value={"data": photo}):
            with self.assertRaisesRegex(d.SpyderError, "Photos and galleries"):
                d.probe(PIN_URL)
        for data in ({}, {"formats": []}, {"formats": [{"ext": "jpg", "height": 720}]}):
            with self.assertRaisesRegex(d.SpyderError, "Photos and galleries"):
                d.build_presets(data, p.PINTEREST)
        for pages in ([{"blocks": []}, {"blocks": []}], [{"blocks": [{"video": {"id": "1"}}, {"video": {"id": "2"}}]}]):
            data = {**PIN_DATA, "story_pin_data": {"pages": pages}}
            with patch.object(PinterestIE, "_call_api", return_value={"data": data}):
                with self.assertRaisesRegex(d.SpyderError, "galleries"):
                    d.probe(PIN_URL)
        story = {"id": "123", "story_pin_data": {"pages": [{"blocks": [{"video": PIN_DATA["videos"]}]}]}}
        with patch.object(PinterestIE, "_call_api", return_value={"data": story}):
            self.assertTrue(d.probe(PIN_URL).presets)

    def test_unknown_codecs_do_not_invent_audio_or_video(self):
        self.assertFalse(any(x.audio_only for x in d.build_presets(self.normalized(PinterestIE()._extract_video(PIN_DATA)), p.PINTEREST)))
        silent = copy.deepcopy(REDDIT_INFO)
        silent["formats"] = silent["formats"][:2]
        for preset in d.build_presets(self.normalized(silent), p.REDDIT):
            self.assertFalse(preset.audio_only)
            self.assertNotIn("+ba", preset.format_selector)
            self.assertEqual(self.selected(silent, preset)["acodec"], "none")
