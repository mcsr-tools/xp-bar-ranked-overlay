import obspython as obs
import urllib.request
import urllib.error
import json
import logging
import sys
import typing


def create_logger(name: str):
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


logger = create_logger(__name__)


SCENE_NAME = "xbro"

SETTING_IS_ENABLED = "enabled"
SETTING_MC_NAME = "mc_name"
SETTING_BTN_GEN = "gen"
SETTING_MC_SOURCE = "mc_source"


MC_XP_BAR_SOURCE_NAME = "xp-bar"
MC_XP_BAR_POS_X = 596.0
MC_XP_BAR_POS_Y = 964.0
MC_XP_BAR_WIDTH = 728
MC_XP_BAR_HEIGHT = 20

MC_XP_BAR_SEGMENTS = 18

MC_XP_BAR_SEGMENT_SOURCE_NAME_PREFIX = "xp-bar-segment"
MC_XP_BAR_SEGMENT_W = 36
MC_XP_BAR_SEGMENT_H = 12
MC_XP_BAR_SEGMENT_GAP = 4
MC_XP_BAR_SEGMENT_BORDER_SIZE = 4

MC_XP_BAR_SEGMENT_COLOR_WIN = 0xFF00FF00
MC_XP_BAR_SEGMENT_COLOR_LOSS = 0xFF0000FF
MC_XP_BAR_SEGMENT_COLOR_DRAW = 0xFFFF0000


TIMER_INTERVAL = 5_000
TIMER_RESIZE_CHECK_INTERVAL = 1_000 // 24


mc_source_name = None
_obs_mc_source = None

mc_name = None

is_enabled = False
is_live = False
is_prev_resize_check_fs = None


def script_properties():
    props = obs.obs_properties_create()
    obs.obs_properties_add_text(
        props,
        SETTING_MC_NAME,
        "MC name",
        obs.OBS_TEXT_DEFAULT,
    )
    obs.obs_properties_add_text(
        props, SETTING_MC_SOURCE, "MC source name", obs.OBS_TEXT_DEFAULT
    )
    obs.obs_properties_add_bool(props, SETTING_IS_ENABLED, "Enable")
    obs.obs_properties_add_button(props, SETTING_BTN_GEN, "Generate scene", gen_scene)
    return props


def script_update(settings):
    global mc_name, is_enabled, mc_source_name, _obs_mc_source

    set_visibility(False)

    mc_name = obs.obs_data_get_string(settings, SETTING_MC_NAME)
    mc_source_name = obs.obs_data_get_string(settings, SETTING_MC_SOURCE)

    if _obs_mc_source:
        obs.obs_source_release(_obs_mc_source)
        _obs_mc_source = None

    is_enabled = obs.obs_data_get_bool(settings, SETTING_IS_ENABLED)

    obs.timer_remove(timer)
    obs.timer_remove(timer_resize_check)
    if is_enabled:
        obs.timer_add(timer, TIMER_INTERVAL)
        obs.timer_add(timer_resize_check, TIMER_RESIZE_CHECK_INTERVAL)


def script_unload():
    global _obs_mc_source
    if _obs_mc_source:
        obs.obs_source_release(_obs_mc_source)
        _obs_mc_source = None


def timer():
    global mc_name, is_live, is_prev_resize_check_fs

    is_live = mcsrranked_is_player_live(mc_name)
    update_visibility()

    if is_live:
        source, scene = get_scene()
        if scene:
            fill_xp_bar_segments_with_match_results(scene)
        if source:
            obs.obs_source_release(source)


def timer_resize_check():
    global is_prev_resize_check_fs, is_live

    if not is_live:
        return

    mc_source = get_mc_source()
    if not mc_source:
        return

    width = obs.obs_source_get_width(mc_source)
    height = obs.obs_source_get_height(mc_source)

    # TODO(GH-2): support resolutions other than 1080p
    is_currently_fs = height == 1080 and width == 1920

    if is_currently_fs != is_prev_resize_check_fs:
        is_prev_resize_check_fs = is_currently_fs
        update_visibility()


def update_visibility():
    global is_live, is_prev_resize_check_fs
    set_visibility(bool(is_live and is_prev_resize_check_fs))


def gen_scene(props, property):
    source, scene = get_scene()

    if not source:
        source = obs.obs_source_create("scene", SCENE_NAME, None, None)
        scene = obs.obs_scene_from_source(source)

    if scene:
        gen_xp_bar(scene)
        gen_xp_bar_segments(scene)
        fill_xp_bar_segments_with_match_results(scene)
    else:
        logger.error(f"failed creating {SCENE_NAME} scene")

    if source:
        obs.obs_source_release(source)


def get_scene():
    source = obs.obs_get_source_by_name(SCENE_NAME)
    if not source:
        return None, None
    return source, obs.obs_scene_from_source(source)


def gen_xp_bar(scene):
    source = obs.obs_get_source_by_name(MC_XP_BAR_SOURCE_NAME)
    if not source:
        source = obs.obs_source_create(
            "image_source", MC_XP_BAR_SOURCE_NAME, None, None
        )

    data = obs.obs_data_create()
    obs.obs_data_set_string(data, "file", script_path() + "xp-bar.png")
    obs.obs_source_update(source, data)
    obs.obs_data_release(data)

    scene_item = obs.obs_scene_find_source(scene, MC_XP_BAR_SOURCE_NAME)
    if not scene_item:
        scene_item = obs.obs_scene_add(scene, source)

    pos = obs.vec2()
    pos.x, pos.y = MC_XP_BAR_POS_X, MC_XP_BAR_POS_Y
    obs.obs_sceneitem_set_pos(scene_item, pos)

    obs.obs_source_release(source)


def gen_xp_bar_segments(scene):
    for i in range(MC_XP_BAR_SEGMENTS):
        name = f"{MC_XP_BAR_SEGMENT_SOURCE_NAME_PREFIX}-{i}"

        source = obs.obs_get_source_by_name(name)
        if not source:
            source = obs.obs_source_create("color_source_v3", name, None, None)

        data = obs.obs_data_create()
        obs.obs_data_set_int(data, "width", MC_XP_BAR_SEGMENT_W)
        obs.obs_data_set_int(data, "height", MC_XP_BAR_SEGMENT_H)
        obs.obs_source_update(source, data)
        obs.obs_data_release(data)

        scene_item = obs.obs_scene_find_source(scene, name)
        if not scene_item:
            scene_item = obs.obs_scene_add(scene, source)

        pos = obs.vec2()
        segment_width = MC_XP_BAR_WIDTH // MC_XP_BAR_SEGMENTS
        # FIXME: end segments drifting/overflowing
        pos.x = MC_XP_BAR_POS_X + MC_XP_BAR_SEGMENT_BORDER_SIZE + i * segment_width
        pos.y = MC_XP_BAR_POS_Y + MC_XP_BAR_SEGMENT_BORDER_SIZE

        obs.obs_sceneitem_set_pos(scene_item, pos)
        obs.obs_sceneitem_set_order(scene_item, obs.OBS_ORDER_MOVE_TOP)

        obs.obs_source_release(source)


def fill_xp_bar_segments_with_match_results(scene):
    global mc_name

    if not mc_name:
        logger.error("fill_xp_bar_segments_with_match_results: mc_name is null")
        return

    match_results = mcsrranked_recent_matches_results(mc_name, MC_XP_BAR_SEGMENTS)
    if not match_results:
        logger.error("faifill_xp_bar_segments_with_match_results: no match results")
        return

    match_results.reverse()
    for i in range(MC_XP_BAR_SEGMENTS):
        name = f"{MC_XP_BAR_SEGMENT_SOURCE_NAME_PREFIX}-{i}"
        segment_source = obs.obs_get_source_by_name(name)

        match_result = match_results[i]
        if not match_result:
            continue

        color = None
        if match_result == "W":
            color = MC_XP_BAR_SEGMENT_COLOR_WIN
        if match_result == "L":
            color = MC_XP_BAR_SEGMENT_COLOR_LOSS
        if match_result == "D":
            color = MC_XP_BAR_SEGMENT_COLOR_DRAW

        settings = obs.obs_source_get_settings(segment_source)
        if match_result:
            obs.obs_data_set_int(settings, "color", color)
            obs.obs_source_update(segment_source, settings)
        else:
            scene_item = obs.obs_scene_find_source(scene, name)
            if scene_item:
                obs.obs_sceneitem_set_visible(scene_item, False)
        obs.obs_data_release(settings)
        obs.obs_source_release(segment_source)


def set_visibility(visibility: bool):
    source, scene = get_scene()
    if not scene:
        return

    items = obs.obs_scene_enum_items(scene)
    if items:
        for item in items:
            obs.obs_sceneitem_set_visible(item, visibility)
        obs.sceneitem_list_release(items)
    obs.obs_source_release(source)


def get_mc_source():
    global _obs_mc_source, mc_source_name
    if not _obs_mc_source and mc_source_name:
        _obs_mc_source = obs.obs_get_source_by_name(mc_source_name)
    return _obs_mc_source


def mcsrranked_recent_matches_results(
    nickname: str, count: int
) -> list[typing.Literal["W", "L", "D"]]:
    logger.debug(
        f"mcsrranked_recent_matches_results: getting {count} recent matches for {nickname}"
    )

    mcsrranked_player_recent_matches_data = fetch_json(
        f"https://api.mcsrranked.com/users/{nickname}/matches?type=2&count={count}&excludedecay=true"
    )

    if not mcsrranked_player_recent_matches_data:
        logger.error(
            f"mcsrranked_recent_matches_results: empty recent matches for {nickname}, do they exist?"
        )
        return

    results = [None] * MC_XP_BAR_SEGMENTS

    for index, match in enumerate(
        mcsrranked_player_recent_matches_data["data"][:MC_XP_BAR_SEGMENTS]
    ):
        result_uuid = match["result"]["uuid"]
        if not result_uuid:
            results[index] = "D"
        else:
            result_player = next(
                filter(
                    lambda player: player["uuid"] == result_uuid,
                    match["players"],
                ),
            )
            if result_player["nickname"].lower() == nickname.lower():
                results[index] = "W"
            else:
                results[index] = "L"

    return results


def mcsrranked_is_player_live(nickname: str):
    logger.debug(f"mcsrranked_is_player_live: called for {nickname}")
    url = "https://api.mcsrranked.com/live"
    logger.debug(f"mcsrranked_is_player_live: fetching {url}")
    json_data = fetch_json(url)

    if json_data == None:
        logger.error(f"mcsrranked_is_player_live: empty live api json data")
        return False

    live_matches = json_data["data"]["liveMatches"]

    logger.debug(
        f"mcsrranked_is_player_live: there are {len(live_matches)} matches going on right now"
    )

    if live_matches:
        for index, match in enumerate(live_matches):
            for player in match["players"]:
                if player["nickname"].lower() == nickname.lower():
                    logger.debug(
                        f"mcsrranked_is_player_live: found player in match {index+1}, current time: {match['currentTime']}"
                    )
                    return True

    logger.debug(f"mcsrranked_is_player_live: {nickname} is not in a match right now")
    return False


def fetch_json(url):
    logger.debug(f"get_json: fetching json data from {url}")

    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            status = response.getcode()
            if status == 200:
                raw_data = response.read().decode("utf-8")
                return json.loads(raw_data)
            logger.error(f"get_json: {url} returned non ok status: {status}")
            return None
    except urllib.error.URLError as e:
        logger.error(f"get_json: Network/URL Error: {e.reason}")
        try:
            error_body = e.read().decode("utf-8")
            logger.error(f"get_json: {e.code}: {e.reason}")
            logger.error(f"get_json: body: {error_body}")
        except Exception:
            logger.error(f"get_json: error {e.code} occurred, but body was unreadable")
    except json.JSONDecodeError:
        logger.error("get_json: Response was not valid JSON.")
    except Exception as e:
        logger.error(f"get_json: Unexpected error: {e}")
    return None
