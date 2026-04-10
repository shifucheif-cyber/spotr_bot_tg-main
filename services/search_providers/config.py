"""Константы, конфигурация дисциплин, API-ключи и словари подсказок."""

import logging
import os

logger = logging.getLogger(__name__)

# --- API keys ---
EXA_API_KEY = os.getenv("EXA_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

logger.info(f"[KEYS] EXA_API_KEY={'SET' if EXA_API_KEY else 'MISSING'}")
logger.info(f"[KEYS] TAVILY_API_KEY={'SET' if TAVILY_API_KEY else 'MISSING'}")
logger.info(f"[KEYS] SERPER_API_KEY={'SET' if SERPER_API_KEY else 'MISSING'}")

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
REQUEST_TIMEOUT = 10
GOOGLE_BACKOFF_SECONDS = max(60, int(os.getenv("GOOGLE_BACKOFF_SECONDS", "900")))
SEARCH_ANALYSIS_PROVIDER = os.getenv("SEARCH_ANALYSIS_PROVIDER", "hybrid").strip().lower()
SEARCH_ANALYSIS_RESULTS_PER_QUERY = max(1, int(os.getenv("SEARCH_ANALYSIS_RESULTS_PER_QUERY", "2")))
SEARCH_ANALYSIS_MAX_SNIPPETS = max(1, int(os.getenv("SEARCH_ANALYSIS_MAX_SNIPPETS", "4")))
SEARCH_SERP_SUPPLEMENT_TERMS = os.getenv(
    "SEARCH_SERP_SUPPLEMENT_TERMS",
    "news injury suspension lineup transfer substitution fatigue form schedule rumors preview",
).strip()
SEARCH_MAX_SITES = max(1, int(os.getenv("SEARCH_MAX_SITES", "4")))
_google_backoff_until = 0.0

RUSSIAN_CONTEXT_HINTS = {
    "рпл", "фнл", "кубок россии", "кхл", "вхл", "мхл", "единая лига втб",
    "суперлига", "вфв", "aca", "rcc", "fight nights", "рtt", "ртт", "снг",
    "восточная европа", "россия", "russia", "russian",
}

RUSSIAN_PARTICIPANT_HINTS = {
    "football": {
        "зенит", "спартак", "цска", "локомотив", "динамо москва", "краснодар", "ростов",
        "рубин", "ахмат", "крылья советов", "оренбург", "факел", "пари нн", "урал", "сочи",
        "zenit", "spartak", "cska", "lokomotiv", "lokomotiv moscow", "dynamo moscow",
        "dinamo moscow", "krasnodar", "rostov", "rubin", "akhmat", "krylia sovetov",
        "orenburg", "fakel", "pari nn", "ural", "sochi",
    },
    "hockey": {
        "ска", "цска", "спартак", "динамо москва", "авангард", "ак барс", "салават юлаев",
        "локомотив", "металлург магнитогорск", "трактор", "северсталь", "торпедо нн", "автомобилист",
        "ska", "cska", "spartak", "dynamo moscow", "dinamo moscow", "avangard", "ak bars",
        "salavat yulaev", "lokomotiv yaroslavl", "metallurg magnitogorsk", "traktor", "severstal",
        "torpedo nizhny novgorod", "avtomobilist",
    },
    "basketball": {
        "зенит", "цска", "уникс", "локомотив кубань", "парма пермь", "самара", "автодор",
        "нижний новгород", "мба", "уралмаш",
        "zenit", "cska", "unics", "lokomotiv kuban", "parma perm", "samara", "avtodor",
        "nizhny novgorod", "mba moscow", "uralmash",
    },
    "volleyball": {
        "зенит казань", "зенит спб", "динамо москва", "локомотив новосибирск", "белогорье",
        "зенит", "динамо", "lokomotiv novosibirsk", "belogorie", "zenit kazan", "zenit st petersburg",
        "dynamo moscow", "zenit", "dynamo",
    },
    "tennis": {
        "медведев", "рублев", "хачанов", "касаткина", "кудерметова", "андреева", "калинская",
        "павлюченкова", "alexandrova", "medvedev", "rublev", "khachanov", "kasatkina",
        "kudermetova", "andreeva", "kalinskaya", "pavlyuchenkova",
    },
    "table_tennis": {
        "шибаев", "карташев", "сидоренко", "полина михайлова", "лилия гуракова",
        "shibaev", "kartashev", "sidorenko", "polina mikhailova", "liliya gurakova",
    },
    "mma": {
        "ислам махачев", "петр ян", "магомед анкалаев", "александр волков", "федор емельяненко",
        "шара буллет", "makhachev", "petr yan", "ankalaev", "volkov", "emelianenko", "shara bullet",
    },
    "boxing": {
        "бивол", "бетербиев", "батыргазиев", "кузямин", "dmitry bivol", "artur beterbiev",
        "batyrgaziev", "kovalev",
    },
    "cs2": {
        "team spirit", "virtus pro", "virtus.pro", "betboom", "forze", "1win", "parivision",
        "дух", "виртус про", "бетбум",
    },
    "dota2": {
        "team spirit", "betboom", "parivision", "virtus pro", "virtus.pro", "9pandas",
        "дух", "бетбум", "виртус про",
    },
    "valorant": {
        "team spirit", "forze", "1win", "дух", "форз", "1вин",
    },
    "lol": {
        "unicorns of love", "virtus pro", "virtus.pro", "vega squadron", "единороги любви", "виртус про",
    },
}

DISCIPLINE_SOURCE_CONFIG = {
    "football": [
        {"site": "premierliga.ru", "label": "RPL Official", "focus": "official lineups protocols player stats", "region": "ru"},
        {"site": "soccer.ru", "label": "Soccer.ru", "focus": "injuries suspensions russian football news", "region": "ru"},
        {"site": "sports.ru", "label": "Sports.ru", "focus": "blogs tactical analysis rpl fnl russian cup", "region": "ru"},
        {"site": "rustat.pro", "label": "Rustat", "focus": "russian football advanced analytics player and team metrics", "region": "ru"},
        {"site": "whoscored.com", "label": "WhoScored", "focus": "player ratings weak defense style of play"},
        {"site": "transfermarkt.com", "label": "Transfermarkt", "focus": "injuries suspensions market value transfers"},
        {"site": "flashscore.com", "label": "Flashscore", "focus": "lineups live stats"},
        {"site": "sofascore.com", "label": "SofaScore", "focus": "live score h2h lineups player ratings"},
        {"site": "fotmob.com", "label": "FotMob", "focus": "live score predicted lineups h2h stats"},
        {"site": "fbref.com", "label": "FBref", "focus": "xg sca pressing advanced stats"},
    ],
    "tennis": [
        {"site": "rtt-tennis.ru", "label": "RTT Tennis", "focus": "russian tennis tour draws rankings juniors adults", "region": "ru"},
        {"site": "tennisexplorer.com", "label": "Tennis Explorer", "focus": "h2h surface results"},
        {"site": "ultimatetennisstatistics.com", "label": "Ultimate Tennis Statistics", "focus": "fatigue first serve second serve physical indicators"},
        {"site": "flashscore.com", "label": "Flashscore Tennis", "focus": "live scores results h2h tennis rankings"},
        {"site": "sofascore.com", "label": "SofaScore Tennis", "focus": "tennis rankings h2h stats recent form"},
        {"site": "atptour.com", "label": "ATP Tour", "focus": "atp rankings stats player profile results"},
        {"site": "wtatennis.com", "label": "WTA", "focus": "wta rankings stats player profile results"},
    ],
    "table_tennis": [
        {"site": "ittf.com", "label": "ITTF", "focus": "official ranking major tournament results"},
        {"site": "tabletennis-guide.com", "label": "Table Tennis Guide", "focus": "equipment pips inverted style matchup"},
        {"site": "tt-rating.ru", "label": "TT Rating", "focus": "russian table tennis ratings results tournaments", "region": "ru"},
        {"site": "flashscore.com", "label": "Flashscore TT", "focus": "table tennis live scores results h2h"},
        {"site": "sofascore.com", "label": "SofaScore TT", "focus": "table tennis results rankings h2h stats"},
    ],
    "mma": [
        {"site": "aca-mma.com", "label": "ACA MMA", "focus": "russian league results fighter stats cards", "region": "ru"},
        {"site": "fighttime.ru", "label": "FightTime", "focus": "cis fighter rankings calendars russian mma news", "region": "ru"},
        {"site": "sherdog.com", "label": "Sherdog", "focus": "fight history reach gyms"},
        {"site": "ufcstats.com", "label": "UFC Stats", "focus": "striking accuracy takedown defense control time"},
        {"site": "tapology.com", "label": "Tapology", "focus": "mma record results upcoming bouts rankings gym"},
        {"site": "championat.com", "label": "Championat MMA", "focus": "mma news previews analysis results", "region": "ru"},
        {"site": "espn.com", "label": "ESPN MMA", "focus": "mma rankings schedule results analysis"},
    ],
    "boxing": [
        {"site": "boxrec.com", "label": "BoxRec", "focus": "verified record titles strength of opposition"},
        {"site": "allboxing.ru", "label": "AllBoxing", "focus": "russian professional boxing news results interviews", "region": "ru"},
        {"site": "tapology.com", "label": "Tapology", "focus": "boxing record results upcoming bouts rankings"},
        {"site": "ringtv.com", "label": "Ring Magazine", "focus": "boxing news rankings analysis previews"},
        {"site": "sports.ru", "label": "Sports.ru", "focus": "boxing news previews analysis results", "region": "ru"},
        {"site": "championat.com", "label": "Championat", "focus": "boxing news previews results analysis", "region": "ru"},
        {"site": "espn.com", "label": "ESPN Boxing", "focus": "boxing rankings schedule results analysis"},
    ],
    "hockey": [
        {"site": "khl.ru", "label": "KHL Official", "focus": "ice time distance shot speed faceoffs official stats", "region": "ru"},
        {"site": "allhockey.ru", "label": "AllHockey", "focus": "transfers insider news player condition locker room", "region": "ru"},
        {"site": "r-hockey.ru", "label": "R-Hockey", "focus": "player database youth leagues career history", "region": "ru"},
        {"site": "vfrhl.ru", "label": "VHL Official", "focus": "vhl standings results match protocols rosters", "region": "ru"},
        {"site": "championat.com", "label": "Championat", "focus": "hockey news previews analysis standings", "region": "ru"},
        {"site": "sport-express.ru", "label": "Sport Express", "focus": "hockey previews injuries lineups analysis", "region": "ru"},
        {"site": "eliteprospects.com", "label": "Elite Prospects", "focus": "rosters transfers goals assists"},
        {"site": "flashscore.com", "label": "Flashscore", "focus": "live scores h2h standings results"},
        {"site": "liveresult.ru", "label": "LiveResult", "focus": "khl vhl europe quick results", "region": "ru"},
    ],
    "basketball": [
        {"site": "vtb-league.com", "label": "VTB United League", "focus": "official vtb league efficiency ratings rosters match protocols", "region": "ru"},
        {"site": "basketball-reference.com", "label": "Basketball-Reference", "focus": "pace offensive efficiency complete nba database"},
        {"site": "euroleaguebasketball.net", "label": "Euroleague Official", "focus": "official euroleague and eurocup stats"},
    ],
    "volleyball": [
        {"site": "volley.ru", "label": "Volley.ru", "focus": "official russian volleyball match protocols attacks blocks", "region": "ru"},
        {"site": "sport.business-gazeta.ru", "label": "BO Sport", "focus": "russian volleyball analysis insider coverage", "region": "ru"},
        {"site": "volleybox.net", "label": "Volleybox", "focus": "rosters transfers leader status"},
    ],
    "cs2": [
        {"site": "cyber.sports.ru", "label": "Cyber Sports.ru", "focus": "cis roster changes interviews regional news", "region": "ru"},
        {"site": "cybersport.ru", "label": "Cybersport.ru", "focus": "regional qualifiers brackets cis match center", "region": "ru"},
        {"site": "hltv.org", "label": "HLTV", "focus": "map pool pistol rounds rating 2.0"},
        {"site": "liquipedia.net", "label": "Liquipedia", "focus": "brackets stand-ins schedule"},
    ],
    "dota2": [
        {"site": "cyber.sports.ru", "label": "Cyber Sports.ru", "focus": "cis roster changes interviews regional news", "region": "ru"},
        {"site": "cybersport.ru", "label": "Cybersport.ru", "focus": "regional qualifiers brackets cis match center", "region": "ru"},
        {"site": "dotabuff.com", "label": "Dotabuff", "focus": "hero meta pub stats pro player form"},
        {"site": "liquipedia.net", "label": "Liquipedia", "focus": "brackets stand-ins schedule"},
    ],
    "valorant": [
        {"site": "cyber.sports.ru", "label": "Cyber Sports.ru", "focus": "cis roster changes interviews regional news", "region": "ru"},
        {"site": "cybersport.ru", "label": "Cybersport.ru", "focus": "regional qualifiers brackets cis match center", "region": "ru"},
        {"site": "vlr.gg", "label": "VLR", "focus": "map stats agent stats match breakdowns"},
        {"site": "liquipedia.net", "label": "Liquipedia", "focus": "brackets roster changes schedule"},
    ],
    "lol": [
        {"site": "cyber.sports.ru", "label": "Cyber Sports.ru", "focus": "cis roster changes interviews regional news", "region": "ru"},
        {"site": "cybersport.ru", "label": "Cybersport.ru", "focus": "regional qualifiers brackets cis match center", "region": "ru"},
        {"site": "oracleselixir.com", "label": "Oracle's Elixir", "focus": "gold per minute objective control advanced stats"},
        {"site": "liquipedia.net", "label": "Liquipedia", "focus": "brackets roster changes schedule"},
    ],
}

DISCIPLINE_SITES = {
    discipline: [entry["site"] for entry in entries]
    for discipline, entries in DISCIPLINE_SOURCE_CONFIG.items()
}

DISCIPLINE_VALIDATION_ALIASES = {
    "football": "football",
    "soccer": "football",
    "футбол": "football",
    "hockey": "hockey",
    "хоккей": "hockey",
    "basketball": "basketball",
    "баскетбол": "basketball",
    "tennis": "tennis",
    "теннис": "tennis",
    "table tennis": "table_tennis",
    "table_tennis": "table_tennis",
    "настольный теннис": "table_tennis",
    "volleyball": "volleyball",
    "волейбол": "volleyball",
    "mma": "mma",
    "мма": "mma",
    "boxing": "boxing",
    "бокс": "boxing",
    "cs2": "cs2",
    "cs 2": "cs2",
    "counter-strike 2": "cs2",
    "counter strike 2": "cs2",
    "dota2": "dota2",
    "dota 2": "dota2",
    "lol": "lol",
    "league of legends": "lol",
    "valorant": "valorant",
}

_DISCIPLINE_SEARCH_LABEL = {
    "football": "football soccer UEFA EPL La Liga Serie A Bundesliga",
    "tennis": "tennis ATP WTA ITF",
    "table_tennis": "table tennis ITTF WTT",
    "hockey": "hockey KHL VHL MHL NHL SHL",
    "basketball": "basketball NBA Euroleague VTB",
    "volleyball": "volleyball CEV SuperLiga",
    "mma": "MMA UFC Bellator PFL",
    "boxing": "boxing WBA WBC IBF WBO",
    "cs2": "CS2 Counter-Strike esports HLTV",
    "dota2": "Dota 2 esports DPC",
    "lol": "League of Legends esports LCK LEC LCS",
    "valorant": "Valorant esports VCT",
}

_REQUIRED_DATA_PATTERNS = {
    "form": r"форм[аы]|form\b|серия|streak|последни[еx]|recent|win\b|loss|побед|поражен|результат|result",
    "h2h": r"h2h|очн[ыеая]|head.to.head|личн[ыеая]\s*встреч|face.?off",
    "injuries": r"травм|injur|дисквал|suspend|отсутств|absent|miss(?:ing)?|выбы[лв]",
    "ranking": r"рейтинг|ranking|seed|посев|position|ATP|WTA|ITTF|HLTV",
    "record": r"рекорд|record|\d+-\d+|побед.*поражен|wins?.*loss",
    "striking": r"striking|удар|accuracy|точност|punch|significant.strikes",
    "reach": r"reach|размах|рук|антропометр|height.*weight|рост.*вес",
    "roster": r"состав|roster|lineup|ростер|игрок|player|team.comp",
}
