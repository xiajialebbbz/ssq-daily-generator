const fs = require("fs");
const https = require("https");
const http = require("http");
const path = require("path");
const crypto = require("crypto");

const PORT = Number(process.env.PORT || 8787);
const ROOT_DIR = __dirname;
const HTML_FILE = path.join(ROOT_DIR, "ssq_daily_generator.html");
const ASSETS_DIR = path.join(ROOT_DIR, "assets");
const DATA_FILE = process.env.SSQ_DATA_FILE
  ? path.resolve(process.env.SSQ_DATA_FILE)
  : path.join(ROOT_DIR, "data", "purchases.json");
const DATA_DIR = path.dirname(DATA_FILE);
const PROFILE_FILE = process.env.SSQ_PROFILE_FILE
  ? path.resolve(process.env.SSQ_PROFILE_FILE)
  : path.join(ROOT_DIR, "data", "ssq_profile.json");
const PROFILE_TTL_MS = 10 * 60 * 1000;
let profileMemoryCache = null;

function ensureDataFile() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  if (!fs.existsSync(DATA_FILE)) {
    fs.writeFileSync(DATA_FILE, "[]\n", "utf8");
  }
}

function readPurchases() {
  ensureDataFile();
  try {
    const text = fs.readFileSync(DATA_FILE, "utf8");
    const data = JSON.parse(text);
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

function writePurchases(records) {
  ensureDataFile();
  const tempFile = `${DATA_FILE}.tmp`;
  fs.writeFileSync(tempFile, `${JSON.stringify(records, null, 2)}\n`, "utf8");
  fs.renameSync(tempFile, DATA_FILE);
}

function send(res, status, body, contentType = "text/plain; charset=utf-8") {
  res.writeHead(status, {
    "Content-Type": contentType,
    "Cache-Control": "no-store"
  });
  res.end(body);
}

function sendJson(res, status, value) {
  send(res, status, JSON.stringify(value), "application/json; charset=utf-8");
}

function requestJson(url) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, {
      timeout: 20000,
      headers: {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Referer": "https://www.cwl.gov.cn/",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest"
      }
    }, (resp) => {
      let body = "";
      resp.setEncoding("utf8");
      resp.on("data", (chunk) => body += chunk);
      resp.on("end", () => {
        try {
          if (resp.statusCode < 200 || resp.statusCode >= 300) {
            reject(new Error(`HTTP ${resp.statusCode}`));
            return;
          }
          resolve(JSON.parse(body));
        } catch (error) {
          reject(error);
        }
      });
    });
    req.on("timeout", () => req.destroy(new Error("request timeout")));
    req.on("error", reject);
  });
}

function parseOfficialRecord(item) {
  const redText = String(item.red || item.redBall || item.redBalls || item.winningRed || "");
  const blueText = String(item.blue || item.blueBall || item.blueBalls || item.winningBlue || "");
  const red = (redText.match(/\d{1,2}/g) || []).map(Number).sort((a, b) => a - b);
  const blueMatch = blueText.match(/\d{1,2}/);
  const blue = blueMatch ? Number(blueMatch[0]) : NaN;
  const issue = String(item.code || item.issue || item.expect || item.lotteryDrawNum || item.drawNum || "");
  const dateText = String(item.date || item.drawTime || item.lotteryDrawTime || item.openTime || "");
  const date = (dateText.match(/\d{4}-\d{2}-\d{2}/) || [dateText.slice(0, 10)])[0];
  const valid = issue &&
    /^\d{4}-\d{2}-\d{2}$/.test(date) &&
    red.length === 6 &&
    new Set(red).size === 6 &&
    red.every((num) => num >= 1 && num <= 33) &&
    blue >= 1 &&
    blue <= 16;
  return valid ? { issue, date, red, blue } : null;
}

async function fetchSsqPage(pageNo, pageSize = 100) {
  const url = new URL("https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice");
  url.searchParams.set("name", "ssq");
  url.searchParams.set("pageNo", String(pageNo));
  url.searchParams.set("pageSize", String(pageSize));
  url.searchParams.set("systemType", "PC");
  return requestJson(url);
}

async function crawlLatestDraws(years = 10) {
  const pageSize = 100;
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - years * 365);
  const first = await fetchSsqPage(1, pageSize);
  const totalPages = Number(first.pageNum || first.pages || 1);
  const records = [];

  for (let pageNo = 1; pageNo <= totalPages; pageNo += 1) {
    const page = pageNo === 1 ? first : await fetchSsqPage(pageNo, pageSize);
    const result = Array.isArray(page.result) ? page.result : [];
    let reachedCutoff = false;
    for (const item of result) {
      const record = parseOfficialRecord(item);
      if (!record) continue;
      const drawDate = new Date(`${record.date}T00:00:00`);
      if (drawDate < cutoff) {
        reachedCutoff = true;
      } else {
        records.push(record);
      }
    }
    if (reachedCutoff || !result.length) break;
  }

  const deduped = new Map();
  records.forEach((record) => deduped.set(record.issue, record));
  return [...deduped.values()].sort((a, b) => b.issue.localeCompare(a.issue));
}

function addCount(map, key) {
  map.set(String(key), (map.get(String(key)) || 0) + 1);
}

function distArray(map) {
  return [...map.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || String(a.value).localeCompare(String(b.value)));
}

function bandValue(value, bands) {
  for (const [low, high] of bands) {
    if (value <= high) return `${low}-${high}`;
  }
  const last = bands[bands.length - 1];
  return `${last[0]}-${last[1]}`;
}

function quantile(values, q) {
  const sorted = [...values].sort((a, b) => a - b);
  const pos = (sorted.length - 1) * q;
  const low = Math.floor(pos);
  const high = Math.ceil(pos);
  return Math.round((sorted[low] + (sorted[high] - sorted[low]) * (pos - low)) * 10) / 10;
}

function consecutiveInfo(nums) {
  let pairs = 0;
  let maxRun = 1;
  let run = 1;
  for (let i = 1; i < nums.length; i += 1) {
    if (nums[i] === nums[i - 1] + 1) {
      pairs += 1;
      run += 1;
      maxRun = Math.max(maxRun, run);
    } else {
      run = 1;
    }
  }
  return { pairs, maxRun };
}

function acValue(nums) {
  const diffs = new Set();
  for (let i = 0; i < nums.length; i += 1) {
    for (let j = i + 1; j < nums.length; j += 1) {
      diffs.add(nums[j] - nums[i]);
    }
  }
  return diffs.size - (nums.length - 1);
}

function tailInfo(nums) {
  const counts = Array(10).fill(0);
  nums.forEach((num) => counts[num % 10] += 1);
  const used = counts.filter((count) => count > 0);
  const digits = counts.map((count, digit) => ({ count, digit }))
    .filter((item) => item.count > 0)
    .map((item) => item.digit);
  return {
    counts,
    distinct: used.length,
    maxSame: Math.max(...used),
    repeatGroups: used.filter((count) => count >= 2).length,
    span: Math.max(...digits) - Math.min(...digits)
  };
}

function computeProfile(records) {
  const redFreq = Array(34).fill(0);
  const blueFreq = Array(17).fill(0);
  const tailFreq = Array(10).fill(0);
  const odd = new Map();
  const size = new Map();
  const zone = new Map();
  const consecutive = new Map();
  const sumBand = new Map();
  const spanBand = new Map();
  const ac = new Map();
  const tailDistinct = new Map();
  const tailMaxSame = new Map();
  const tailRepeat = new Map();
  const tailSpan = new Map();
  const sums = [];
  const spans = [];

  records.forEach((record) => {
    const reds = record.red;
    reds.forEach((num) => redFreq[num] += 1);
    blueFreq[record.blue] += 1;
    const tails = tailInfo(reds);
    tails.counts.forEach((count, digit) => tailFreq[digit] += count);
    const oddCount = reds.filter((num) => num % 2 === 1).length;
    const smallCount = reds.filter((num) => num <= 16).length;
    const zones = [
      reds.filter((num) => num <= 11).length,
      reds.filter((num) => num >= 12 && num <= 22).length,
      reds.filter((num) => num >= 23).length
    ];
    const total = reds.reduce((acc, num) => acc + num, 0);
    const span = reds[5] - reds[0];
    const con = consecutiveInfo(reds);
    addCount(odd, oddCount);
    addCount(size, smallCount);
    addCount(zone, zones.join("-"));
    addCount(consecutive, con.pairs);
    addCount(sumBand, bandValue(total, [[29,73],[74,86],[87,100],[101,114],[115,128],[129,172]]));
    addCount(spanBand, bandValue(span, [[5,17],[18,22],[23,26],[27,30],[31,32]]));
    addCount(ac, acValue(reds));
    addCount(tailDistinct, tails.distinct);
    addCount(tailMaxSame, tails.maxSame);
    addCount(tailRepeat, tails.repeatGroups);
    addCount(tailSpan, tails.span);
    sums.push(total);
    spans.push(span);
  });

  return {
    sourceFile: "cwl.gov.cn/findDrawNotice",
    syncedAt: new Date().toISOString(),
    drawCount: records.length,
    issueStart: records[records.length - 1]?.issue || "",
    issueEnd: records[0]?.issue || "",
    dateStart: records[records.length - 1]?.date || "",
    dateEnd: records[0]?.date || "",
    latestDraw: records[0] || null,
    redFreq: redFreq.slice(1),
    blueFreq: blueFreq.slice(1),
    tailFreq,
    oddDist: distArray(odd),
    sizeDist: distArray(size),
    zoneDist: distArray(zone),
    consecutiveDist: distArray(consecutive),
    sumBandDist: distArray(sumBand),
    spanBandDist: distArray(spanBand),
    acDist: distArray(ac),
    tailDistinctDist: distArray(tailDistinct),
    tailMaxSameDist: distArray(tailMaxSame),
    tailRepeatDist: distArray(tailRepeat),
    tailSpanDist: distArray(tailSpan),
    sumStats: { min: Math.min(...sums), q10: quantile(sums, .1), q25: quantile(sums, .25), median: quantile(sums, .5), q75: quantile(sums, .75), q90: quantile(sums, .9), max: Math.max(...sums) },
    spanStats: { min: Math.min(...spans), q10: quantile(spans, .1), q25: quantile(spans, .25), median: quantile(spans, .5), q75: quantile(spans, .75), q90: quantile(spans, .9), max: Math.max(...spans) }
  };
}

function readProfileCache() {
  try {
    const text = fs.readFileSync(PROFILE_FILE, "utf8");
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function writeProfileCache(profile) {
  fs.mkdirSync(path.dirname(PROFILE_FILE), { recursive: true });
  const tempFile = `${PROFILE_FILE}.tmp`;
  fs.writeFileSync(tempFile, `${JSON.stringify(profile, null, 2)}\n`, "utf8");
  fs.renameSync(tempFile, PROFILE_FILE);
}

async function getSyncedProfile(force = false) {
  const now = Date.now();
  if (!force && profileMemoryCache && now - new Date(profileMemoryCache.syncedAt).getTime() < PROFILE_TTL_MS) {
    return { ...profileMemoryCache, syncStatus: "memory-cache" };
  }
  const cached = readProfileCache();
  if (!force && cached && now - new Date(cached.syncedAt).getTime() < PROFILE_TTL_MS) {
    profileMemoryCache = cached;
    return { ...cached, syncStatus: "file-cache" };
  }
  try {
    const records = await crawlLatestDraws(10);
    if (records.length < 1000) {
      throw new Error(`too few records: ${records.length}`);
    }
    const profile = computeProfile(records);
    writeProfileCache(profile);
    profileMemoryCache = profile;
    return { ...profile, syncStatus: "fresh" };
  } catch (error) {
    if (cached) {
      return { ...cached, syncStatus: "stale-cache", syncError: error.message };
    }
    throw error;
  }
}

function parseBetsFromSmsLines(smsLines) {
  const source = smsLines.join("\n").replace(/\\/g, "");
  const bets = [];
  for (const match of source.matchAll(/(\d{12})\*(\d{2})/g)) {
    const red = match[1].match(/\d{2}/g).map(Number).sort((a, b) => a - b);
    const blue = Number(match[2]);
    const redValid = red.length === 6 &&
      new Set(red).size === 6 &&
      red.every((num) => num >= 1 && num <= 33);
    if (redValid && blue >= 1 && blue <= 16) {
      bets.push({ red, blue });
    }
  }
  return bets;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.setEncoding("utf8");
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 1024 * 1024) {
        reject(new Error("request body too large"));
        req.destroy();
      }
    });
    req.on("end", () => resolve(body));
    req.on("error", reject);
  });
}

async function handleApi(req, res, pathname) {
  if (pathname === "/api/profile") {
    if (req.method !== "GET") {
      sendJson(res, 405, { error: "method not allowed" });
      return;
    }
    try {
      const requestUrl = new URL(req.url, `http://${req.headers.host || "localhost"}`);
      const profile = await getSyncedProfile(requestUrl.searchParams.get("force") === "1");
      sendJson(res, 200, profile);
    } catch (error) {
      sendJson(res, 502, { error: error.message });
    }
    return;
  }

  if (pathname !== "/api/purchases") {
    sendJson(res, 404, { error: "not found" });
    return;
  }

  if (req.method === "GET") {
    sendJson(res, 200, readPurchases());
    return;
  }

  if (req.method === "POST") {
    try {
      const payload = JSON.parse(await readBody(req));
      const smsLines = Array.isArray(payload.smsLines)
        ? payload.smsLines.map((line) => String(line).trim()).filter(Boolean)
        : [];
      const bets = parseBetsFromSmsLines(smsLines);
      if (!smsLines.length || !bets.length) {
        sendJson(res, 400, { error: "no valid bets" });
        return;
      }

      const records = readPurchases();
      records.push({
        id: crypto.randomUUID(),
        createdAt: new Date().toISOString(),
        smsLines,
        bets,
        betCount: bets.length,
        lastDraw: payload.lastDraw || null,
        source: payload.savedFrom || "ssq_daily_generator"
      });
      writePurchases(records);
      sendJson(res, 200, records);
    } catch (error) {
      sendJson(res, 400, { error: error.message });
    }
    return;
  }

  sendJson(res, 405, { error: "method not allowed" });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  if (url.pathname.startsWith("/api/")) {
    await handleApi(req, res, url.pathname);
    return;
  }

  if (req.method !== "GET") {
    send(res, 405, "method not allowed");
    return;
  }

  if (url.pathname === "/" || url.pathname === "/ssq_daily_generator.html") {
    send(res, 200, fs.readFileSync(HTML_FILE), "text/html; charset=utf-8");
    return;
  }

  if (url.pathname.startsWith("/assets/")) {
    const assetPath = path.resolve(ROOT_DIR, `.${decodeURIComponent(url.pathname)}`);
    if (!assetPath.startsWith(ASSETS_DIR) || !fs.existsSync(assetPath)) {
      send(res, 404, "not found");
      return;
    }
    const ext = path.extname(assetPath).toLowerCase();
    const contentType = ext === ".svg"
      ? "image/svg+xml; charset=utf-8"
      : "application/octet-stream";
    send(res, 200, fs.readFileSync(assetPath), contentType);
    return;
  }

  send(res, 404, "not found");
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`双色球选号应用已启动：http://127.0.0.1:${PORT}/`);
  console.log(`购买记录文件：${DATA_FILE}`);
  console.log(`开奖缓存文件：${PROFILE_FILE}`);
});
