const DRAFT_KEY = "campus_jarvis_frontend_bundle";
const ACCOUNT_STORAGE_KEY = "campus_jarvis_account";
const LEGACY_USER_STORAGE_KEY = "campus_jarvis_user_id";
const DAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const COURSE_COLORS = ["blue", "green", "amber", "rose", "violet"];
const MAX_PUSH_TIMES = 20;
const PAGE_PARAMS = new URLSearchParams(window.location.search);
const DEMO_MODE = PAGE_PARAMS.get("demo") === "1";
const DEMO_USER_ID = "demo-video-user";

const refs = {
  form: document.querySelector("#settingsForm"),
  userId: document.querySelector("#userId"),
  nickname: document.querySelector("#nickname"),
  saveState: document.querySelector("#saveState"),
  identityState: document.querySelector("#identityState"),
  loginOverlay: document.querySelector("#loginOverlay"),
  accountInput: document.querySelector("#accountInput"),
  accountLoginBtn: document.querySelector("#accountLoginBtn"),
  loginState: document.querySelector("#loginState"),
  accountSwitchBtn: document.querySelector("#accountSwitchBtn"),
  accountName: document.querySelector("#accountName"),
  accountBindInput: document.querySelector("#accountBindInput"),
  accountBindBtn: document.querySelector("#accountBindBtn"),
  basicState: document.querySelector("#basicState"),
  basicEditBtn: document.querySelector("#basicEditBtn"),
  basicCancelBtn: document.querySelector("#basicCancelBtn"),
  basicSaveBtn: document.querySelector("#basicSaveBtn"),
  addTodoBtn: document.querySelector("#addTodoBtn"),
  addCourseBtn: document.querySelector("#addCourseBtn"),
  addPushBtn: document.querySelector("#addPushBtn"),
  importCourseBtn: document.querySelector("#importCourseBtn"),
  courseImportInput: document.querySelector("#courseImportInput"),
  todoList: document.querySelector("#todoList"),
  courseList: document.querySelector("#courseList"),
  pushList: document.querySelector("#pushList"),
  scheduleGrid: document.querySelector("#scheduleGrid"),
  todoTemplate: document.querySelector("#todoTemplate"),
  courseTemplate: document.querySelector("#courseTemplate"),
  pushTemplate: document.querySelector("#pushTemplate"),
  toast: document.querySelector("#toast"),
  todoCount: document.querySelector("#todoCount"),
  courseCount: document.querySelector("#courseCount"),
  pushCount: document.querySelector("#pushCount"),
  nextDeadlineTitle: document.querySelector("#nextDeadlineTitle"),
  nextDeadlineTime: document.querySelector("#nextDeadlineTime"),
  profileScore: document.querySelector("#profileScore"),
  profileProgress: document.querySelector("#profileProgress"),
  profileHint: document.querySelector("#profileHint"),
  todayActionList: document.querySelector("#todayActionList"),
  apiState: document.querySelector("#apiState"),
  apiStateDetail: document.querySelector("#apiStateDetail"),
  chatIdentityCard: document.querySelector("#chatIdentityCard"),
  chatFocusCard: document.querySelector("#chatFocusCard"),
  chatProfileCard: document.querySelector("#chatProfileCard"),
  briefBtn: document.querySelector("#briefBtn"),
  clearChatBtn: document.querySelector("#clearChatBtn"),
  briefPanel: document.querySelector("#briefPanel"),
  briefText: document.querySelector("#briefText"),
  chatMessages: document.querySelector("#chatMessages"),
  chatInput: document.querySelector("#chatInput"),
  chatSendBtn: document.querySelector("#chatSendBtn"),
  chatHint: document.querySelector("#chatHint"),
  demoBanner: document.querySelector("#demoBanner"),
};

let currentBundle = null;
let baselineBundle = null;
let basicEditing = false;
let basicDirty = false;
let dragSelection = null;
let currentUserId = "";
let currentAccount = "";
let pendingBindUserId = "";
let identitySource = "unknown";
let demoStep = 0;

const DEMO_PROFILE = {
  name: "张三",
  studentId: "2026123456",
  college: "仪器科学与工程学院",
  major: "智能感知工程",
  grade: "2026级",
  phone: "13800001234",
  email: "zhangsan@example.edu.cn",
  interests: ["人工智能", "智能感知", "医学工程"],
  projectDirection: "AI + 医学影像辅助分析",
};

const DEMO_REPLIES = [
  `根据你填写的兴趣方向，我先帮你筛了一遍近期比较匹配的竞赛。\n\n你的兴趣画像：人工智能、智能感知、医学工程。\n\n推荐优先级如下：\n1. 中国机器人及人工智能大赛：适合 AI 应用、机器人感知和智能系统方向，展示性强。\n2. 全国大学生生物医学工程创新设计竞赛：更贴合“AI + 医学工程 / 医学影像辅助分析”，适合做跨学科项目。\n3. 大学生创新创业训练计划 AI+医疗方向：适合把课程项目继续打磨成长期作品。\n\n如果从你的方向匹配度来看，我会优先建议关注“全国大学生生物医学工程创新设计竞赛”。`,
  `全国大学生生物医学工程创新设计竞赛主要面向生物医学工程、医学信息、智能医疗设备、医学影像处理、辅助诊疗和健康工程等方向。\n\n为什么适合你：\n- 你的专业是智能感知工程，可以从传感、数据采集和智能分析切入。\n- 你的兴趣包含人工智能和医学工程，适合做 AI 辅助医学影像分析、可穿戴健康监测、康复训练评估等选题。\n- 竞赛作品通常重视“真实问题 + 工程实现 + 展示效果”，适合黑客松后继续沉淀。\n\n报名通常需要：负责人信息、队伍成员、学院专业、联系方式、项目方向、项目简介和指导老师信息。\n\n我可以继续帮你整理报名信息，并先生成一份可提交的报名草稿。`,
  `可以。我先根据报名要求核对需要填写的信息。\n\n报名该比赛通常需要以下内容：\n- 竞赛名称\n- 负责人姓名、学号、学院、专业、年级\n- 手机号、邮箱\n- 项目方向和项目简介\n- 队伍成员与指导老师信息\n\n我已经从你的用户画像中读取到：\n- 姓名：${DEMO_PROFILE.name}\n- 学号：${DEMO_PROFILE.studentId}\n- 学院：${DEMO_PROFILE.college}\n- 专业：${DEMO_PROFILE.major}\n- 年级：${DEMO_PROFILE.grade}\n- 项目方向：${DEMO_PROFILE.projectDirection}\n\n请确认以上信息是否无误。确认后，我会打开报名页面并帮你预填信息，最后一步仍由你手动确认提交。`,
  `收到确认。我正在打开报名页面，并根据你的用户画像自动填写报名信息。\n\n为避免误操作，系统只会完成预填，不会自动点击最终提交按钮。请你在报名页确认无误后手动点击“确认提交”。`,
];

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function makeLocalId(prefix) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function normalizeAccount(value) {
  return String(value || "").trim().toLowerCase();
}

function draftKey(userId = currentUserId) {
  return `${DRAFT_KEY}_${userId || "missing-user"}`;
}

function showToast(message) {
  refs.toast.textContent = message;
  refs.toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => refs.toast.classList.remove("show"), 2600);
}

function setSaveState(text, mode = "saved") {
  refs.saveState.textContent = text;
  refs.saveState.classList.toggle("saved", mode === "saved");
  refs.saveState.classList.toggle("dirty", mode === "dirty");
}

function showFatal(message) {
  setSaveState("缺少用户标识", "dirty");
  refs.form.classList.add("disabled-form");
  const panel = document.createElement("section");
  panel.className = "fatal-state";
  panel.textContent = message;
  document.querySelector(".workspace").prepend(panel);
}

function clampInt(value, min, max, fallback) {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) return fallback;
  return Math.min(Math.max(parsed, min), max);
}

function parseJsonArray(value, fallback = []) {
  if (Array.isArray(value)) return value;
  if (value === null || value === undefined || value === "") return fallback;
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : fallback;
  } catch {
    return String(value)
      .split(/[,，\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
}

function parseJsonObject(value, fallback = {}) {
  if (value && typeof value === "object" && !Array.isArray(value)) return value;
  if (!value) return fallback;
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function textToArray(value) {
  return String(value || "")
    .split(/[,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function arrayToText(value) {
  return parseJsonArray(value, []).join(", ");
}

function toInputDateTime(value) {
  if (!value) return "";
  return String(value).replace(" ", "T").slice(0, 16);
}

function fromInputDateTime(value) {
  return value ? value.replace("T", " ") : "";
}

function formatDateTime(value) {
  if (!value) return "未设置";
  return String(value).replace("T", " ").slice(0, 16);
}

function parseLocalDate(value) {
  if (!value) return null;
  const normalized = String(value).replace(" ", "T");
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function isToday(value) {
  const date = parseLocalDate(value);
  if (!date) return false;
  const now = new Date();
  return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
}

function shortDateTime(value) {
  const text = formatDateTime(value);
  return text === "未设置" ? text : text.replace(/^20\d{2}-/, "");
}

function normalizeTime(value) {
  const match = String(value || "").trim().match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return "";
  const hour = clampInt(match[1], 0, 23, 0);
  const minute = clampInt(match[2], 0, 59, 0);
  return String(hour).padStart(2, "0") + ":" + String(minute).padStart(2, "0");
}

function timeToMinutes(value) {
  const normalized = normalizeTime(value);
  if (!normalized) return 0;
  const [hour, minute] = normalized.split(":").map(Number);
  return hour * 60 + minute;
}

function sortTimes(times) {
  return [...new Set((times || []).map(normalizeTime).filter(Boolean))]
    .sort((left, right) => timeToMinutes(left) - timeToMinutes(right))
    .slice(0, MAX_PUSH_TIMES);
}

function parseTimes(value) {
  const raw = Array.isArray(value) ? value : String(value || "").split(/[,，\n]/);
  return sortTimes(raw);
}

function parseWeekdays(value) {
  const raw = Array.isArray(value) ? value : String(value || "").split(/[,，\s]/);
  return [...new Set(raw.map((item) => clampInt(item, 1, 7, 0)).filter(Boolean))].sort((a, b) => a - b);
}

function priorityLabel(value) {
  return {
    "1": "1 最高",
    "2": "2 较高",
    "3": "3 普通",
    "4": "4 较低",
    "5": "5 最低",
  }[String(value)] || "3 普通";
}

function statusLabel(value) {
  return {
    pending: "进行中",
    done: "已完成",
    cancelled: "已取消",
  }[value] || "进行中";
}

function frequencyLabel(value) {
  return {
    daily: "每天",
    weekly: "每周",
    date: "指定日期",
  }[value] || "每天";
}

function pushTypeLabel(value) {
  return value === "interest" ? "感兴趣新闻" : "自定义文本";
}

function weekdaysText(values) {
  const parsed = parseWeekdays(values);
  return parsed.length ? parsed.map((day) => DAYS[day - 1]).join("、") : "未设置";
}

function createEmptyBundle(userId = currentUserId) {
  return {
    user: {
      user_id: userId,
      nickname: "",
    },
    profile: {
      user_id: userId,
      real_name: "",
      gender: "",
      birthday: "",
      school: "东南大学",
      campus: "",
      college: "",
      major: "",
      grade: "",
      interests: "[]",
      goals: "[]",
      preferences: "{}",
      personal_description: "",
      assistant_persona: "",
    },
    deadlines: [],
    courses: [],
    push_settings: {
      user_id: userId,
      content_preferences: "[]",
      daily_ddl_enabled: 1,
      push_frequency: "daily",
      push_times: '["08:30"]',
      quiet_hours_start: "",
      quiet_hours_end: "",
      deadline_lookahead_days: 7,
    },
  };
}

function createDemoBundle() {
  const userId = DEMO_USER_ID;
  return {
    account: "demo",
    user_id: userId,
    user: {
      user_id: userId,
      nickname: DEMO_PROFILE.name,
    },
    profile: {
      user_id: userId,
      real_name: DEMO_PROFILE.name,
      gender: "",
      birthday: "",
      school: "东南大学",
      campus: "九龙湖",
      college: DEMO_PROFILE.college,
      major: DEMO_PROFILE.major,
      grade: DEMO_PROFILE.grade,
      interests: JSON.stringify(DEMO_PROFILE.interests),
      goals: JSON.stringify(["参加跨学科竞赛", "完成 AI+医学工程项目"]),
      preferences: JSON.stringify({
        interests: DEMO_PROFILE.interests,
        goals: ["参加跨学科竞赛", "完成 AI+医学工程项目"],
        campus: "九龙湖",
      }),
      personal_description: "关注人工智能、智能感知与医学工程交叉方向。",
      assistant_persona: "直接、清晰，优先给出下一步行动。",
    },
    deadlines: [
      {
        deadline_id: "demo-ddl-1",
        title: "生物医学工程创新设计竞赛报名",
        description: "确认队伍信息，提交项目简介。",
        start_time: "",
        deadline_time: "2026-06-12 20:00",
        priority: "2",
        status: "pending",
        category: "竞赛",
        source_type: "demo",
        source_ref: "",
      },
    ],
    courses: [],
    push_settings: {
      user_id: userId,
      content_preferences: JSON.stringify([
        {
          push_id: "demo-push-1",
          type: "custom",
          title: "竞赛提醒",
          content: "关注 AI、智能感知、医学工程相关竞赛。",
          frequency: "daily",
          date: "",
          weekdays: [],
          repeat_count: 1,
          times: ["08:30"],
        },
      ]),
      daily_ddl_enabled: 1,
      push_frequency: "daily",
      push_times: JSON.stringify(["08:30"]),
      quiet_hours_start: "",
      quiet_hours_end: "",
      deadline_lookahead_days: 7,
    },
    web_context: [],
  };
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function demoThinkingDelay() {
  return 2500 + Math.floor(Math.random() * 1500);
}

function nextDemoReply() {
  const index = Math.min(demoStep, DEMO_REPLIES.length);
  demoStep += 1;
  if (index < DEMO_REPLIES.length) return DEMO_REPLIES[index];
  return "本次报名流程已经完成。我会继续跟踪材料提交截止时间、队伍信息补全和后续通知。";
}

function openDemoRegistrationPage() {
  window.setTimeout(() => {
    window.location.href = "/demo/register?autofill=1";
  }, 900);
}

function normalizeDeadline(item = {}) {
  return {
    deadline_id: item.deadline_id || "",
    title: item.title || "",
    description: item.description || "",
    start_time: item.start_time || "",
    deadline_time: item.deadline_time || "",
    priority: String(clampInt(item.priority, 1, 5, 3)),
    status: item.status || "pending",
    category: item.category || "",
    source_type: item.source_type || "manual",
    source_ref: item.source_ref || "",
  };
}

function normalizeSection(value, fallback) {
  const match = String(value || "").match(/\d+/);
  return clampInt(match ? match[0] : value, 1, 13, fallback);
}

function normalizeCourse(item = {}, index = 0) {
  const start = normalizeSection(item.start_section ?? item.start_time, 1);
  const end = normalizeSection(item.end_section ?? item.end_time, Math.min(13, start + 1));
  const localId = item.local_id || (item.course_id ? `course-id-${item.course_id}` : `course-${index}`);
  return {
    local_id: localId,
    course_id: item.course_id || "",
    course_name: item.course_name || "",
    day_of_week: String(clampInt(item.day_of_week, 1, 7, 1)),
    start_section: String(start),
    end_section: String(Math.max(start, end)),
    start_time: String(start),
    end_time: String(Math.max(start, end)),
    location: item.location || "",
    teacher: item.teacher || "",
    weeks: item.weeks || "",
    note: item.note || "",
    color: item.color || COURSE_COLORS[index % COURSE_COLORS.length],
  };
}

function normalizePushItem(item = {}, index = 0) {
  if (typeof item === "string") {
    return {
      push_id: `push-${index}`,
      type: "interest",
      title: item,
      content: item,
      frequency: "daily",
      date: "",
      weekdays: [],
      repeat_count: 1,
      times: ["08:30"],
    };
  }

  const rawTimes = item.times ?? item.push_times ?? ["08:30"];
  const times = parseTimes(rawTimes);
  return {
    push_id: item.push_id || item.id || `push-${index}`,
    type: item.type === "interest" ? "interest" : "custom",
    title: item.title || "",
    content: item.content || item.keywords || "",
    frequency: ["daily", "weekly", "date"].includes(item.frequency) ? item.frequency : "daily",
    date: item.date || "",
    weekdays: parseWeekdays(item.weekdays || []),
    repeat_count: clampInt(item.repeat_count, 1, MAX_PUSH_TIMES, times.length || 1),
    times,
  };
}

function parsePushItems(pushSettings = {}) {
  const items = parseJsonArray(pushSettings.content_preferences, []);
  return items.map(normalizePushItem);
}

function normalizeBundle(bundle) {
  const source = bundle || {};
  const id = source.user?.user_id || source.profile?.user_id || source.user_id || currentUserId;
  if (!id) throw new Error("缺少用户标识 user_id。");
  currentUserId = id;
  const empty = createEmptyBundle(id);
  const user = { ...empty.user, ...(source.user || {}), user_id: id };
  const profile = { ...empty.profile, ...(source.profile || {}), user_id: id };
  const pushSettings = { ...empty.push_settings, ...(source.push_settings || {}), user_id: id };
  const pushItems = parsePushItems(pushSettings);

  profile.school = profile.school || "东南大学";
  profile.interests = JSON.stringify(parseJsonArray(profile.interests, []), null, 0);
  profile.goals = JSON.stringify(parseJsonArray(profile.goals, []), null, 0);
  profile.preferences = JSON.stringify(parseJsonObject(profile.preferences, {}), null, 0);
  pushSettings.content_preferences = JSON.stringify(pushItems);

  return {
    account: source.account || currentAccount || "",
    user,
    profile,
    deadlines: (source.deadlines || []).map(normalizeDeadline),
    courses: (source.courses || []).map(normalizeCourse),
    push_settings: pushSettings,
    web_context: Array.isArray(source.web_context) ? source.web_context : [],
  };
}

function readLocalDraft() {
  try {
    return JSON.parse(localStorage.getItem(draftKey()) || "null");
  } catch {
    return null;
  }
}

function writeLocalDraft(bundle) {
  if (currentAccount) localStorage.setItem(ACCOUNT_STORAGE_KEY, currentAccount);
  localStorage.setItem(draftKey(bundle.user.user_id), JSON.stringify(bundle));
  localStorage.setItem(LEGACY_USER_STORAGE_KEY, bundle.user.user_id);
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`接口返回格式异常（HTTP ${response.status}）`);
  }
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `请求失败（HTTP ${response.status}）`);
  }
  return data;
}

function fillBasicInfo(bundle) {
  const profile = bundle.profile;
  refs.userId.value = bundle.user.user_id || profile.user_id || "";
  refs.accountName.value = bundle.account || currentAccount || "";
  refs.accountBindInput.value = "";
  refs.nickname.value = bundle.user.nickname || "";

  for (const field of [
    "real_name",
    "gender",
    "birthday",
    "school",
    "campus",
    "college",
    "major",
    "grade",
    "personal_description",
    "assistant_persona",
  ]) {
    if (refs.form.elements[field]) refs.form.elements[field].value = profile[field] || "";
  }

  refs.form.elements.school.value = profile.school || "东南大学";
  refs.form.elements.interests.value = arrayToText(profile.interests);
  refs.form.elements.goals.value = arrayToText(profile.goals);
}

function collectBasic() {
  const userId = refs.userId.value || currentUserId;
  if (!userId) throw new Error("缺少用户标识 user_id，请从 /信息设置 链接进入。");
  const interests = textToArray(refs.form.elements.interests.value);
  const goals = textToArray(refs.form.elements.goals.value);
  return {
    user_id: userId,
    user: {
      user_id: userId,
      nickname: refs.nickname.value.trim(),
    },
    profile: {
      user_id: userId,
      real_name: refs.form.elements.real_name.value.trim(),
      gender: refs.form.elements.gender.value,
      birthday: refs.form.elements.birthday.value,
      school: refs.form.elements.school.value.trim() || "东南大学",
      campus: refs.form.elements.campus.value,
      college: refs.form.elements.college.value.trim(),
      major: refs.form.elements.major.value.trim(),
      grade: refs.form.elements.grade.value.trim(),
      interests: JSON.stringify(interests),
      goals: JSON.stringify(goals),
      preferences: JSON.stringify({
        interests,
        goals,
        campus: refs.form.elements.campus.value,
      }),
      personal_description: refs.form.elements.personal_description.value.trim(),
      assistant_persona: refs.form.elements.assistant_persona.value.trim(),
    },
  };
}

function setBasicDirty(nextDirty) {
  basicDirty = nextDirty;
  refs.basicState.textContent = basicEditing ? (basicDirty ? "未保存" : "编辑中") : "浏览";
  refs.basicState.classList.toggle("dirty", basicDirty);
  refs.basicState.classList.toggle("saved", !basicDirty && !basicEditing);
}

function setBasicEditing(nextEditing) {
  basicEditing = nextEditing;
  refs.basicEditBtn.classList.toggle("hidden", basicEditing);
  refs.basicCancelBtn.classList.toggle("hidden", !basicEditing);
  refs.basicSaveBtn.classList.toggle("hidden", !basicEditing);

  for (const control of document.querySelectorAll("[data-basic-editable]")) {
    control.disabled = !basicEditing;
  }
  setBasicDirty(basicDirty);
}

function setControlValue(item, field, value) {
  const control = item.querySelector(`input[data-field="${field}"], select[data-field="${field}"], textarea[data-field="${field}"]`);
  if (control) control.value = value ?? "";
}

function getControlMap(item) {
  const row = {};
  for (const control of item.querySelectorAll("input[data-field], select[data-field], textarea[data-field]")) {
    row[control.dataset.field] = control.value.trim();
  }
  return row;
}

function setSingleChoiceGroup(group, value) {
  group.dataset.value = String(value || "3");
  for (const button of group.querySelectorAll("button")) {
    button.classList.toggle("active", button.dataset.value === group.dataset.value);
  }
}

function setMultiChoiceGroup(group, values) {
  const selected = new Set(parseWeekdays(values).map(String));
  group.dataset.value = [...selected].join(",");
  for (const button of group.querySelectorAll("button")) {
    button.classList.toggle("active", selected.has(button.dataset.value));
  }
}

function collectPushTimes(item) {
  return sortTimes([...item.querySelectorAll(".push-time-input")].map((input) => input.value));
}

function updatePushFrequencyFields(item) {
  const frequency = item.querySelector('select[data-field="frequency"]')?.value || "daily";
  item.querySelector(".push-date-field")?.classList.toggle("frequency-hidden", frequency !== "date");
  item.querySelector(".push-weekdays-field")?.classList.toggle("frequency-hidden", frequency !== "weekly");
}

function updateTimeAddState(item) {
  const addButton = item.querySelector(".time-add-button");
  if (!addButton) return;
  const count = item.querySelectorAll(".push-time-input").length;
  addButton.disabled = !item.classList.contains("editing") || count >= MAX_PUSH_TIMES;
}

function renderPushTimeList(item, times) {
  const list = item.querySelector(".push-time-list");
  if (!list) return;
  list.replaceChildren();
  const values = sortTimes(times);
  for (const value of values) {
    list.appendChild(createPushTimeRow(item, value));
  }
  updateTimeAddState(item);
}

function createPushTimeRow(item, value) {
  const row = document.createElement("div");
  row.className = "push-time-row";

  const input = document.createElement("input");
  input.className = "push-time-input";
  input.type = "time";
  input.value = normalizeTime(value) || "08:30";
  input.disabled = !item.classList.contains("editing");

  const removeButton = document.createElement("button");
  removeButton.className = "remove-time";
  removeButton.type = "button";
  removeButton.textContent = "x";
  removeButton.title = "删除推送时间";
  removeButton.setAttribute("aria-label", "删除推送时间");
  removeButton.disabled = !item.classList.contains("editing");

  input.addEventListener("change", () => {
    input.value = normalizeTime(input.value);
    renderPushTimeList(item, collectPushTimes(item));
    updatePushPresentation(item);
  });

  removeButton.addEventListener("click", () => {
    if (!item.classList.contains("editing")) return;
    const count = item.querySelectorAll(".push-time-input").length;
    if (count <= 1) {
      showToast("至少保留一个推送时间");
      return;
    }
    row.remove();
    renderPushTimeList(item, collectPushTimes(item));
    updatePushPresentation(item);
  });

  row.append(input, removeButton);
  return row;
}

function addPushTime(item) {
  const times = collectPushTimes(item);
  if (times.length >= MAX_PUSH_TIMES) {
    showToast("最多添加二十个推送时间");
    return;
  }
  const last = times.length ? timeToMinutes(times[times.length - 1]) : 8 * 60 + 30;
  const next = (last + 60) % (24 * 60);
  const nextTime = `${String(Math.floor(next / 60)).padStart(2, "0")}:${String(next % 60).padStart(2, "0")}`;
  renderPushTimeList(item, [...times, nextTime]);
  updatePushPresentation(item);
}

function detailField(label, value, full = false) {
  const wrapper = document.createElement("div");
  wrapper.className = full ? "detail-field detail-full" : "detail-field";
  const labelEl = document.createElement("span");
  labelEl.textContent = label;
  const valueEl = document.createElement("strong");
  valueEl.textContent = value || "未填写";
  wrapper.append(labelEl, valueEl);
  return wrapper;
}

function setItemControlsEnabled(item, enabled) {
  for (const control of item.querySelectorAll(".edit-fields input[data-field], .edit-fields select[data-field], .edit-fields textarea[data-field]")) {
    if (control.type !== "hidden") control.disabled = !enabled;
  }
  for (const input of item.querySelectorAll(".push-time-input")) {
    input.disabled = !enabled;
  }
  for (const button of item.querySelectorAll(".priority-group button, .weekday-group button, .remove-time")) {
    button.disabled = !enabled;
  }
  updateTimeAddState(item);
}

function itemKind(item) {
  return item.dataset.kind;
}

function rowFromItem(item) {
  const kind = itemKind(item);
  const row = getControlMap(item);
  if (kind === "todo") {
    row.priority = item.querySelector(".priority-group").dataset.value || "3";
    row.start_time = fromInputDateTime(row.start_time);
    row.deadline_time = fromInputDateTime(row.deadline_time);
    return normalizeDeadline(row);
  }
  if (kind === "course") {
    const start = clampInt(row.start_section, 1, 13, 1);
    const end = clampInt(row.end_section, 1, 13, start);
    return normalizeCourse({
      ...row,
      local_id: row.local_id || makeLocalId("course"),
      start_section: start,
      end_section: Math.max(start, end),
      start_time: String(start),
      end_time: String(Math.max(start, end)),
    });
  }

  const frequency = row.frequency || "daily";
  const weekdays = frequency === "weekly" ? parseWeekdays(item.querySelector(".weekday-group").dataset.value) : [];
  const times = collectPushTimes(item);
  return normalizePushItem({
    ...row,
    push_id: row.push_id || makeLocalId("push"),
    date: frequency === "date" ? row.date : "",
    frequency,
    weekdays,
    times,
    repeat_count: times.length,
  });
}

function fillTodoItem(item, todo) {
  const normalized = normalizeDeadline(todo);
  setControlValue(item, "deadline_id", normalized.deadline_id);
  setControlValue(item, "title", normalized.title);
  setControlValue(item, "category", normalized.category);
  setControlValue(item, "start_time", toInputDateTime(normalized.start_time));
  setControlValue(item, "deadline_time", toInputDateTime(normalized.deadline_time));
  setControlValue(item, "status", normalized.status);
  setControlValue(item, "description", normalized.description);
  setSingleChoiceGroup(item.querySelector(".priority-group"), normalized.priority);
  updateTodoPresentation(item);
}

function fillCourseItem(item, course) {
  const normalized = normalizeCourse(course);
  for (const [field, value] of Object.entries(normalized)) {
    setControlValue(item, field, value);
  }
  item.dataset.key = normalized.local_id;
  updateCoursePresentation(item);
}

function fillPushItem(item, push) {
  const normalized = normalizePushItem(push);
  setControlValue(item, "push_id", normalized.push_id);
  setControlValue(item, "type", normalized.type);
  setControlValue(item, "title", normalized.title);
  setControlValue(item, "content", normalized.content);
  setControlValue(item, "frequency", normalized.frequency);
  setControlValue(item, "date", normalized.date);
  setMultiChoiceGroup(item.querySelector(".weekday-group"), normalized.weekdays);
  renderPushTimeList(item, normalized.times.length ? normalized.times : ["08:30"]);
  updatePushFrequencyFields(item);
  updatePushPresentation(item);
}

function updateTodoPresentation(item) {
  const row = rowFromItem(item);
  item.querySelector(".item-title").textContent = row.title || "未命名待办";
  item.querySelector(".item-meta").textContent = [
    row.category || "未分类",
    priorityLabel(row.priority),
    formatDateTime(row.deadline_time),
  ].join(" · ");

  const detail = item.querySelector(".detail-read");
  detail.replaceChildren(
    detailField("类别", row.category),
    detailField("开始时间", formatDateTime(row.start_time)),
    detailField("结束时间", formatDateTime(row.deadline_time)),
    detailField("状态", statusLabel(row.status)),
    detailField("重要程度", priorityLabel(row.priority)),
    detailField("详细描述", row.description, true)
  );
}

function updateCoursePresentation(item) {
  const row = rowFromItem(item);
  item.dataset.key = row.local_id;
  item.querySelector(".item-title").textContent = row.course_name || "未命名课程";
  item.querySelector(".item-meta").textContent = [
    DAYS[Number(row.day_of_week) - 1],
    `${row.start_section}-${row.end_section}节`,
    row.location || "未填写地点",
  ].join(" · ");

  const detail = item.querySelector(".detail-read");
  detail.replaceChildren(
    detailField("星期", DAYS[Number(row.day_of_week) - 1]),
    detailField("节次", `${row.start_section}-${row.end_section}节`),
    detailField("颜色", row.color),
    detailField("老师", row.teacher),
    detailField("地点", row.location),
    detailField("周次", row.weeks),
    detailField("备注", row.note, true)
  );
}

function updatePushPresentation(item) {
  const row = rowFromItem(item);
  item.querySelector(".item-title").textContent = row.title || "未命名推送";
  item.querySelector(".item-meta").textContent = [
    pushTypeLabel(row.type),
    frequencyLabel(row.frequency),
    row.times.length ? row.times.join("、") : "未设置推送时间",
  ].join(" · ");

  const detail = item.querySelector(".detail-read");
  const fields = [
    detailField("类型", pushTypeLabel(row.type)),
    detailField("推送方式", frequencyLabel(row.frequency)),
  ];
  if (row.frequency === "weekly") fields.push(detailField("每周周几", weekdaysText(row.weekdays)));
  if (row.frequency === "date") fields.push(detailField("指定日期", row.date));
  fields.push(
    detailField("推送时间", row.times.length ? row.times.join("、") : "未设置"),
    detailField("推送内容 / 兴趣关键词", row.content, true)
  );
  detail.replaceChildren(...fields);
  updatePushFrequencyFields(item);
  updateTimeAddState(item);
}

function updateItemPresentation(item) {
  const kind = itemKind(item);
  if (kind === "todo") updateTodoPresentation(item);
  if (kind === "course") {
    updateCoursePresentation(item);
    refreshScheduleFromDom();
  }
  if (kind === "push") updatePushPresentation(item);
  refreshSnapshotFromDom();
}

function setItemEditing(item, editing) {
  if (editing) {
    item.dataset.baseline = JSON.stringify(rowFromItem(item));
    item.classList.add("expanded", "editing");
  } else {
    item.classList.remove("editing");
  }
  setItemControlsEnabled(item, editing);
}

function cancelItemEdit(item) {
  if (item.dataset.isNew === "true") {
    item.remove();
    renderEmptyStates();
  } else if (item.dataset.baseline) {
    const row = JSON.parse(item.dataset.baseline);
    if (itemKind(item) === "todo") fillTodoItem(item, row);
    if (itemKind(item) === "course") fillCourseItem(item, row);
    if (itemKind(item) === "push") fillPushItem(item, row);
    setItemEditing(item, false);
  } else {
    setItemEditing(item, false);
  }
  refreshScheduleFromDom();
  refreshSnapshotFromDom();
}

function attachChoiceHandlers(item) {
  for (const group of item.querySelectorAll(".priority-group")) {
    group.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-value]");
      if (!button || !item.classList.contains("editing")) return;
      setSingleChoiceGroup(group, button.dataset.value);
      updateItemPresentation(item);
    });
  }

  for (const group of item.querySelectorAll(".weekday-group")) {
    group.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-value]");
      if (!button || !item.classList.contains("editing")) return;
      button.classList.toggle("active");
      const values = [...group.querySelectorAll("button.active")].map((activeButton) => activeButton.dataset.value);
      setMultiChoiceGroup(group, values);
      updateItemPresentation(item);
    });
  }
}

function attachItemHandlers(item) {
  item.querySelector(".item-main").addEventListener("click", () => {
    if (item.classList.contains("editing")) return;
    item.classList.toggle("expanded");
  });

  item.querySelector(".edit-item").addEventListener("click", (event) => {
    event.stopPropagation();
    setItemEditing(item, true);
  });

  item.querySelector(".complete-item")?.addEventListener("click", async (event) => {
    event.stopPropagation();
    if (itemKind(item) !== "todo") return;
    setControlValue(item, "status", "done");
    updateTodoPresentation(item);
    try {
      await persistCurrentDom("待办已完成");
    } catch (error) {
      showToast(error.message);
    }
  });

  item.querySelector(".remove-item").addEventListener("click", async (event) => {
    event.stopPropagation();
    const title = item.querySelector(".item-title").textContent;
    if (!window.confirm(`删除“${title}”？`)) return;
    item.remove();
    renderEmptyStates();
    await persistCurrentDom("已删除");
  });

  item.querySelector(".save-item").addEventListener("click", async () => {
    try {
      validateSingleItem(item);
      await persistCurrentDom("已保存");
    } catch (error) {
      showToast(error.message);
    }
  });

  item.querySelector(".cancel-item").addEventListener("click", () => cancelItemEdit(item));

  item.querySelector(".time-add-button")?.addEventListener("click", () => {
    if (!item.classList.contains("editing")) return;
    addPushTime(item);
  });

  item.addEventListener("input", (event) => {
    if (!item.classList.contains("editing")) return;
    if (event.target.matches("input[data-field], textarea[data-field]")) updateItemPresentation(item);
  });

  item.addEventListener("change", (event) => {
    if (!item.classList.contains("editing")) return;
    if (event.target.matches("select[data-field], input[data-field]")) updateItemPresentation(item);
  });

  attachChoiceHandlers(item);
}

function createTodoItem(todo = {}, options = {}) {
  const item = refs.todoTemplate.content.cloneNode(true).querySelector(".todo-item");
  fillTodoItem(item, todo);
  attachItemHandlers(item);
  item.dataset.isNew = options.isNew ? "true" : "false";
  item.classList.toggle("expanded", Boolean(options.expanded));
  setItemEditing(item, Boolean(options.editing));
  return item;
}

function createCourseItem(course = {}, options = {}) {
  const item = refs.courseTemplate.content.cloneNode(true).querySelector(".course-item");
  fillCourseItem(item, course);
  attachItemHandlers(item);
  item.dataset.isNew = options.isNew ? "true" : "false";
  item.classList.toggle("expanded", Boolean(options.expanded));
  setItemEditing(item, Boolean(options.editing));
  return item;
}

function createPushItem(push = {}, options = {}) {
  const item = refs.pushTemplate.content.cloneNode(true).querySelector(".push-item");
  fillPushItem(item, push);
  attachItemHandlers(item);
  item.dataset.isNew = options.isNew ? "true" : "false";
  item.classList.toggle("expanded", Boolean(options.expanded));
  setItemEditing(item, Boolean(options.editing));
  return item;
}

function addEmptyState(container, text) {
  for (const item of container.querySelectorAll(".empty-state")) item.remove();
  if (container.querySelector(".config-item")) return;
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.textContent = text;
  container.appendChild(empty);
}

function renderEmptyStates() {
  addEmptyState(refs.todoList, "还没有待办事项");
  addEmptyState(refs.courseList, "还没有课程");
  addEmptyState(refs.pushList, "还没有推送内容");
}

function fillList(container, items, factory) {
  container.replaceChildren();
  for (const item of items) container.appendChild(factory(item));
}

function fillUI(bundle) {
  currentBundle = normalizeBundle(bundle);
  currentAccount = currentBundle.account || currentAccount || "";
  fillBasicInfo(currentBundle);
  fillList(refs.todoList, currentBundle.deadlines, createTodoItem);
  fillList(refs.courseList, currentBundle.courses, createCourseItem);
  fillList(refs.pushList, parsePushItems(currentBundle.push_settings), createPushItem);
  renderSchedule(currentBundle.courses);
  renderChatHistory(currentBundle.web_context);
  updateIdentityState();
  renderEmptyStates();
  refreshSnapshotFromDom();
  refreshDashboardFromDom();
  setBasicEditing(false);
  setBasicDirty(false);
}

function updateIdentityState() {
  const accountText = currentAccount ? `账号：${currentAccount}` : "账号未绑定";
  const sourceText = identitySource === "demo" ? "身份已识别" : identitySource === "qq" ? "QQ 链接进入" : identitySource === "account" ? "账号登录" : "身份已识别";
  refs.identityState.textContent = `${sourceText} · ${accountText}`;
  const bindRow = refs.accountBindInput?.closest(".bind-row");
  const shouldShowBind = identitySource === "qq" && !currentAccount;
  if (bindRow) {
    bindRow.classList.toggle("hidden", !shouldShowBind);
  }
  if (refs.accountBindInput) {
    refs.accountBindInput.disabled = !shouldShowBind;
    refs.accountBindInput.placeholder = shouldShowBind ? "设置网页账号" : "账号已确定";
    if (!shouldShowBind) refs.accountBindInput.value = "";
  }
  if (refs.chatIdentityCard) {
    refs.chatIdentityCard.textContent = identitySource === "demo" ? DEMO_PROFILE.name : identitySource === "qq" ? "QQ 免登录" : currentAccount ? `账号 ${currentAccount}` : "未登录";
  }
}

function setChatBusy(busy) {
  refs.chatSendBtn.disabled = busy;
  refs.chatInput.disabled = busy;
  refs.chatHint.textContent = busy ? "思考中" : "网页会话";
  refs.chatHint.classList.toggle("dirty", busy);
  refs.chatHint.classList.toggle("saved", !busy);
}

function appendChatMessage(role, content, options = {}) {
  const message = document.createElement("article");
  message.className = `chat-message ${role === "user" ? "user" : "assistant"}`;
  if (options.loading) message.classList.add("loading");

  const avatar = document.createElement("span");
  avatar.className = "chat-avatar";
  avatar.textContent = role === "user" ? "你" : "AI";

  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";
  if (options.loading) {
    const spinner = document.createElement("span");
    spinner.className = "chat-spinner";
    spinner.setAttribute("aria-hidden", "true");

    const label = document.createElement("span");
    label.className = "chat-loading-text";
    label.textContent = content;
    bubble.append(spinner, label);
  } else {
    bubble.textContent = content;
  }

  message.append(avatar, bubble);
  refs.chatMessages.appendChild(message);
  refs.chatMessages.scrollTop = refs.chatMessages.scrollHeight;
  return message;
}

function replaceChatMessage(message, role, content) {
  if (!message || !message.isConnected) {
    appendChatMessage(role, content);
    return;
  }
  message.className = `chat-message ${role === "user" ? "user" : "assistant"}`;
  const avatar = message.querySelector(".chat-avatar");
  const bubble = message.querySelector(".chat-bubble");
  if (avatar) avatar.textContent = role === "user" ? "你" : "AI";
  if (bubble) bubble.textContent = content;
  refs.chatMessages.scrollTop = refs.chatMessages.scrollHeight;
}

function renderChatHistory(messages = []) {
  refs.chatMessages.replaceChildren();
  const visibleMessages = messages.filter((item) => item && item.role && item.content);
  if (!visibleMessages.length) {
    appendChatMessage(
      "assistant",
      DEMO_MODE
        ? "你好，我是你的导员。你可以直接问我校园通知、竞赛机会、DDL 和办事流程。我会结合你的专业、兴趣和当前事项，给出更适合你的下一步建议。"
        : "这里是 Campus Jarvis 的网页聊天入口。它和 QQ bot 共享用户资料，但网页会话上下文单独保存。你可以问：我是谁、今天有什么DDL、有什么推送。"
    );
    return;
  }
  for (const item of visibleMessages.slice(-30)) {
    appendChatMessage(item.role === "user" ? "user" : "assistant", item.content);
  }
}

function renderTodayActions(actions) {
  refs.todayActionList.replaceChildren();
  if (!actions.length) {
    const empty = document.createElement("p");
    empty.className = "today-empty";
    empty.textContent = "今天没有强提醒事项";
    refs.todayActionList.appendChild(empty);
    return;
  }
  for (const action of actions.slice(0, 4)) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `today-action ${action.level || "normal"}`;
    item.innerHTML = `<strong>${action.title}</strong><span>${action.meta}</span>`;
    item.addEventListener("click", () => {
      if (action.tab) requestTabSwitch(action.tab);
    });
    refs.todayActionList.appendChild(item);
  }
}

function profileCompleteness() {
  const profile = collectBasic();
  const todos = collectTodos({ allowIncomplete: true }).filter((item) => item.title);
  const courses = collectCourses({ allowIncomplete: true }).filter((item) => item.course_name);
  const pushes = collectPushItems({ allowIncomplete: true }).filter((item) => item.title);
  const checks = [
    Boolean(profile.user.nickname),
    Boolean(profile.profile.campus),
    Boolean(profile.profile.college),
    Boolean(profile.profile.major),
    Boolean(profile.profile.grade),
    textToArray(refs.form.elements.interests.value).length > 0,
    textToArray(refs.form.elements.goals.value).length > 0,
    todos.length > 0,
    courses.length > 0,
    pushes.length > 0,
  ];
  const done = checks.filter(Boolean).length;
  return Math.round((done / checks.length) * 100);
}

function refreshDashboardFromDom() {
  let todos = [];
  let courses = [];
  let pushes = [];
  try {
    todos = collectTodos({ allowIncomplete: true }).filter((item) => item.title);
    courses = collectCourses({ allowIncomplete: true }).filter((item) => item.course_name);
    pushes = collectPushItems({ allowIncomplete: true }).filter((item) => item.title);
  } catch {
    return;
  }

  const openTodos = todos
    .filter((item) => item.status !== "done" && item.status !== "cancelled")
    .sort((a, b) => String(a.deadline_time).localeCompare(String(b.deadline_time)));
  const todayTodos = openTodos.filter((item) => isToday(item.deadline_time));
  const today = new Date().getDay() || 7;
  const todayCourses = courses.filter((item) => Number(item.day_of_week) === today);
  const score = profileCompleteness();
  const next = openTodos[0];

  refs.profileScore.textContent = `${score}%`;
  refs.profileProgress.style.width = `${score}%`;
  refs.profileHint.textContent =
    score >= 80 ? "画像已经比较完整，适合做个性化简报。" : "继续补全专业、兴趣、课表和推送偏好，建议会更准。";
  refs.chatProfileCard.textContent = `${score}%`;
  refs.chatFocusCard.textContent = next ? `${next.title} · ${shortDateTime(next.deadline_time)}` : "暂无待办";
  refs.chatIdentityCard.textContent = identitySource === "demo" ? DEMO_PROFILE.name : identitySource === "qq" ? "QQ 免登录" : currentAccount ? `账号 ${currentAccount}` : "未登录";

  const actions = [];
  if (todayTodos.length) {
    actions.push({
      title: `${todayTodos.length} 个今日 DDL`,
      meta: todayTodos[0].title,
      level: "urgent",
      tab: "todos",
    });
  } else if (next) {
    actions.push({
      title: "最近 DDL",
      meta: `${next.title} · ${shortDateTime(next.deadline_time)}`,
      level: "normal",
      tab: "todos",
    });
  }
  if (todayCourses.length) {
    actions.push({
      title: `${todayCourses.length} 门今日课程`,
      meta: todayCourses.slice(0, 2).map((item) => item.course_name).join("、"),
      level: "normal",
      tab: "schedule",
    });
  }
  if (pushes.length) {
    actions.push({
      title: `${pushes.length} 个推送偏好`,
      meta: pushes.slice(0, 2).map((item) => item.title).join("、"),
      level: "soft",
      tab: "push",
    });
  }
  if (score < 80) {
    actions.push({
      title: "补全画像",
      meta: "完善专业、兴趣和目标",
      level: "soft",
      tab: "basic",
    });
  }
  renderTodayActions(actions);
}

async function checkHealth() {
  try {
    const health = await fetchJson("/api/health");
    const counts = health.database?.counts || {};
    refs.apiState.textContent = health.ok ? "接口正常" : "接口异常";
    refs.apiStateDetail.textContent = `用户 ${counts.users_table ?? "-"} · DDL ${counts.plan_table ?? "-"} · 推送 ${counts.notification_table ?? "-"}`;
    refs.apiState.classList.toggle("danger-text", !health.ok);
  } catch (error) {
    refs.apiState.textContent = "接口异常";
    refs.apiStateDetail.textContent = error.message;
    refs.apiState.classList.add("danger-text");
  }
}

async function sendChatMessage(overrideMessage = "") {
  const presetMessage = typeof overrideMessage === "string" ? overrideMessage : "";
  const message = (presetMessage || refs.chatInput.value).trim();
  if (!message || !currentUserId) return;

  refs.chatInput.value = "";
  appendChatMessage("user", message);
  const loadingMessage = appendChatMessage("assistant", "正在思考...", { loading: true });
  setChatBusy(true);

  if (DEMO_MODE) {
    try {
      await delay(demoThinkingDelay());
      const reply = nextDemoReply();
      replaceChatMessage(loadingMessage, "assistant", reply);
      if (currentBundle) {
        const context = Array.isArray(currentBundle.web_context) ? currentBundle.web_context : [];
        context.push({ role: "user", content: message });
        context.push({ role: "assistant", content: reply });
        currentBundle.web_context = context.slice(-40);
      }
      if (demoStep === 4) {
        openDemoRegistrationPage();
      }
    } finally {
      setChatBusy(false);
      refs.chatInput.focus();
    }
    return;
  }

  try {
    const data = await fetchJson("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: currentUserId, message }),
    });
    replaceChatMessage(loadingMessage, "assistant", data.reply || "收到。");
    if (Array.isArray(data.context) && currentBundle) {
      currentBundle.web_context = data.context;
      writeLocalDraft(currentBundle);
    }
  } catch (error) {
    replaceChatMessage(loadingMessage, "assistant", `接口暂时不可用：${error.message}`);
  } finally {
    setChatBusy(false);
    refs.chatInput.focus();
  }
}

async function generateDailyBrief() {
  if (!currentUserId) return;
  refs.briefBtn.disabled = true;
  refs.briefText.textContent = "正在整理你的今日安排...";
  refs.briefPanel.classList.remove("hidden");
  try {
    const data = await fetchJson("/api/daily_brief", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: currentUserId }),
    });
    const brief = data.brief || "今天没有生成到有效简报。";
    refs.briefText.textContent = brief;
    appendChatMessage("assistant", brief);
    if (Array.isArray(data.context) && currentBundle) {
      currentBundle.web_context = data.context;
      writeLocalDraft(currentBundle);
    }
  } catch (error) {
    refs.briefText.textContent = `简报生成失败：${error.message}`;
  } finally {
    refs.briefBtn.disabled = false;
  }
}

async function clearChatHistory() {
  if (!currentUserId) return;
  if (!window.confirm("清空网页聊天记录？QQ bot 的对话上下文不会受影响。")) return;
  try {
    await fetchJson("/api/chat/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: currentUserId }),
    });
    if (currentBundle) {
      currentBundle.web_context = [];
      writeLocalDraft(currentBundle);
    }
    renderChatHistory([]);
    refs.briefPanel.classList.add("hidden");
    showToast("网页聊天记录已清空");
  } catch (error) {
    showToast(`清空失败：${error.message}`);
  }
}

function collectTodos({ allowIncomplete = false } = {}) {
  const todos = [];
  for (const item of refs.todoList.querySelectorAll(".todo-item")) {
    const row = rowFromItem(item);
    const touched = row.deadline_id || row.title || row.description || row.start_time || row.deadline_time || row.category;
    if (!touched) continue;
    if (!allowIncomplete && (!row.title || !row.deadline_time)) {
      throw new Error("每条待办都需要填写名称和结束时间。");
    }
    todos.push(row);
  }
  return todos;
}

function collectCourses({ allowIncomplete = false } = {}) {
  const courses = [];
  for (const item of refs.courseList.querySelectorAll(".course-item")) {
    const row = rowFromItem(item);
    const touched = row.course_id || row.course_name || row.teacher || row.location || row.weeks || row.note;
    if (!touched) continue;
    if (!allowIncomplete && !row.course_name) {
      throw new Error("每条课程都需要填写课程名。");
    }
    if (!allowIncomplete && Number(row.end_section) < Number(row.start_section)) {
      throw new Error("课程结束节次不能早于开始节次。");
    }
    courses.push(row);
  }
  return courses;
}

function collectPushItems({ allowIncomplete = false } = {}) {
  const pushes = [];
  for (const item of refs.pushList.querySelectorAll(".push-item")) {
    const row = rowFromItem(item);
    const touched = row.push_id || row.title || row.content || row.date;
    if (!touched && item.dataset.isNew === "true") continue;
    if (!allowIncomplete && !row.title) {
      throw new Error("每条推送都需要填写标题。");
    }
    if (!allowIncomplete && row.frequency === "weekly" && row.weekdays.length === 0) {
      throw new Error("每周推送需要选择周几。");
    }
    if (!allowIncomplete && row.frequency === "date" && !row.date) {
      throw new Error("指定日期推送需要填写日期。");
    }
    if (!allowIncomplete && row.times.length === 0) {
      throw new Error("每条推送至少需要一个推送时间。");
    }
    pushes.push(row);
  }
  return pushes;
}

function validateSingleItem(item) {
  const kind = itemKind(item);
  const row = rowFromItem(item);
  if (kind === "todo" && (!row.title || !row.deadline_time)) {
    throw new Error("待办需要填写名称和结束时间。");
  }
  if (kind === "course" && !row.course_name) {
    throw new Error("课程需要填写课程名。");
  }
  if (kind === "course" && Number(row.end_section) < Number(row.start_section)) {
    throw new Error("课程结束节次不能早于开始节次。");
  }
  if (kind === "push" && !row.title) {
    throw new Error("推送需要填写标题。");
  }
  if (kind === "push" && row.frequency === "weekly" && row.weekdays.length === 0) {
    throw new Error("每周推送需要选择周几。");
  }
  if (kind === "push" && row.frequency === "date" && !row.date) {
    throw new Error("指定日期推送需要填写日期。");
  }
  if (kind === "push" && row.times.length === 0) {
    throw new Error("每条推送至少需要一个推送时间。");
  }
  if (kind === "push" && row.times.length > MAX_PUSH_TIMES) {
    throw new Error("每条推送最多二十个推送时间。");
  }
}

function collectPayload({ allowIncomplete = false } = {}) {
  const basic = collectBasic();
  const todos = collectTodos({ allowIncomplete });
  const courses = collectCourses({ allowIncomplete });
  const pushItems = collectPushItems({ allowIncomplete });
  const pushTimes = [...new Set(pushItems.flatMap((item) => item.times))];
  return normalizeBundle({
    account: currentAccount,
    user_id: basic.user_id,
    user: basic.user,
    profile: basic.profile,
    deadlines: todos,
    courses,
    push_settings: {
      user_id: basic.user_id,
      content_preferences: JSON.stringify(pushItems),
      daily_ddl_enabled: pushItems.length ? 1 : 0,
      push_frequency: pushItems[0]?.frequency || "daily",
      push_times: JSON.stringify(pushTimes.length ? pushTimes : ["08:30"]),
      quiet_hours_start: "",
      quiet_hours_end: "",
      deadline_lookahead_days: 7,
    },
    web_context: currentBundle?.web_context || [],
  });
}

async function saveToBackend(payload) {
  if (location.protocol === "file:") return false;
  const bundle = await fetchJson("/api/user/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (bundle.user?.user_id) {
    payload.user.user_id = bundle.user.user_id;
    payload.profile.user_id = bundle.user.user_id;
    payload.push_settings.user_id = bundle.user.user_id;
  }
  if (bundle.account !== undefined) {
    payload.account = bundle.account;
  }
  return true;
}

function syncSummary(payload) {
  const nickname = payload.user?.nickname ? "基本信息" : "基本信息未完整";
  const todos = payload.deadlines?.filter((item) => item.title).length || 0;
  const courses = payload.courses?.filter((item) => item.course_name).length || 0;
  const pushes = parsePushItems(payload.push_settings).filter((item) => item.title).length;
  return `${nickname} · DDL ${todos} · 课程 ${courses} · 推送 ${pushes}`;
}

async function persistPayload(payload, message) {
  setSaveState("保存中", "dirty");
  let backendSaved = false;
  try {
    backendSaved = await saveToBackend(payload);
  } catch (error) {
    showToast("已保存前端草稿，后端接口暂未同步：" + error.message);
  }

  currentBundle = normalizeBundle(payload);
  baselineBundle = clone(currentBundle);
  writeLocalDraft(currentBundle);
  fillUI(currentBundle);
  setSaveState(backendSaved ? "已同步" : "本地草稿", backendSaved ? "saved" : "dirty");
  showToast(backendSaved ? `${message}：${syncSummary(currentBundle)}` : `${message}，已保存在前端草稿`);
  return true;
}

async function persistCurrentDom(message = "已保存") {
  const payload = collectPayload();
  return persistPayload(payload, message);
}

async function saveBasic() {
  try {
    const payload = collectPayload({ allowIncomplete: true });
    await persistPayload(payload, "基本信息已保存");
    setBasicEditing(false);
    setBasicDirty(false);
    return true;
  } catch (error) {
    showToast(error.message);
    return false;
  }
}

function renderSchedule(courses) {
  refs.scheduleGrid.replaceChildren();

  const corner = document.createElement("div");
  corner.className = "schedule-head corner-cell";
  corner.textContent = "节次";
  refs.scheduleGrid.appendChild(corner);

  DAYS.forEach((day, index) => {
    const head = document.createElement("div");
    head.className = "schedule-head";
    head.style.gridColumn = String(index + 2);
    head.style.gridRow = "1";
    head.textContent = day;
    refs.scheduleGrid.appendChild(head);
  });

  for (let section = 1; section <= 13; section += 1) {
    const period = document.createElement("div");
    period.className = "period-cell";
    period.style.gridColumn = "1";
    period.style.gridRow = String(section + 1);
    period.textContent = String(section);
    refs.scheduleGrid.appendChild(period);

    for (let day = 1; day <= 7; day += 1) {
      const slot = document.createElement("div");
      slot.className = "slot-cell";
      slot.style.gridColumn = String(day + 1);
      slot.style.gridRow = String(section + 1);
      slot.dataset.day = String(day);
      slot.dataset.section = String(section);
      refs.scheduleGrid.appendChild(slot);
    }
  }

  courses.filter((course) => course.course_name).forEach((course, index) => {
    const normalized = normalizeCourse(course, index);
    const start = clampInt(normalized.start_section, 1, 13, 1);
    const end = clampInt(normalized.end_section, 1, 13, start);
    const day = clampInt(normalized.day_of_week, 1, 7, 1);
    const card = document.createElement("article");
    card.className = `course-card ${normalized.color || COURSE_COLORS[index % COURSE_COLORS.length]}`;
    card.dataset.key = normalized.local_id;
    card.style.gridColumn = String(day + 1);
    card.style.gridRow = `${start + 1} / ${Math.max(start, end) + 2}`;

    const title = document.createElement("strong");
    title.textContent = normalized.course_name;
    const meta = document.createElement("span");
    meta.textContent = [normalized.teacher, normalized.location].filter(Boolean).join(" · ") || "未填写教师/地点";
    const weeks = document.createElement("span");
    weeks.textContent = normalized.weeks || `${start}-${Math.max(start, end)}节`;
    card.append(title, meta, weeks);
    card.addEventListener("click", (event) => {
      event.stopPropagation();
      focusCourseItem(normalized.local_id);
    });
    refs.scheduleGrid.appendChild(card);

    for (let section = start; section <= Math.max(start, end); section += 1) {
      const slot = refs.scheduleGrid.querySelector(`.slot-cell[data-day="${day}"][data-section="${section}"]`);
      if (slot) slot.classList.add("has-course");
    }
  });
}

function refreshScheduleFromDom() {
  renderSchedule(collectCourses({ allowIncomplete: true }));
}

function refreshSnapshotFromDom() {
  const todos = collectTodos({ allowIncomplete: true });
  const courses = collectCourses({ allowIncomplete: true });
  const pushItems = collectPushItems({ allowIncomplete: true });

  const todoRows = todos.filter((item) => item.title);
  refs.todoCount.textContent = String(todoRows.length);
  refs.courseCount.textContent = String(courses.filter((item) => item.course_name).length);
  refs.pushCount.textContent = String(pushItems.filter((item) => item.title).length);

  const next = todoRows
    .filter((item) => item.status !== "done" && item.deadline_time)
    .sort((a, b) => String(a.deadline_time).localeCompare(String(b.deadline_time)))[0];
  refs.nextDeadlineTitle.textContent = next ? next.title : "暂无";
  refs.nextDeadlineTime.textContent = next ? formatDateTime(next.deadline_time) : "待添加";
  refreshDashboardFromDom();
}

function clearScheduleSelection() {
  for (const slot of refs.scheduleGrid.querySelectorAll(".slot-cell.selecting")) {
    slot.classList.remove("selecting");
  }
}

function paintScheduleSelection(day, start, end) {
  clearScheduleSelection();
  const low = Math.min(start, end);
  const high = Math.max(start, end);
  for (let section = low; section <= high; section += 1) {
    const slot = refs.scheduleGrid.querySelector(`.slot-cell[data-day="${day}"][data-section="${section}"]`);
    if (slot) slot.classList.add("selecting");
  }
}

function insertCourseFromSelection(day, start, end) {
  clearScheduleSelection();
  const low = Math.min(start, end);
  const high = Math.max(start, end);
  appendCourse({
    local_id: makeLocalId("course"),
    day_of_week: String(day),
    start_section: String(low),
    end_section: String(high),
    start_time: String(low),
    end_time: String(high),
    color: COURSE_COLORS[refs.courseList.querySelectorAll(".course-item").length % COURSE_COLORS.length],
  });
  showToast(`${DAYS[day - 1]} ${low}-${high} 节已准备添加课程`);
}

function focusCourseItem(key) {
  showTab("schedule");
  const item = refs.courseList.querySelector(`.course-item[data-key="${CSS.escape(key)}"]`);
  if (!item) return;
  item.classList.add("expanded");
  item.scrollIntoView({ behavior: "smooth", block: "center" });
}

function showTab(name) {
  for (const button of document.querySelectorAll(".tab-button")) {
    button.classList.toggle("active", button.dataset.tab === name);
  }
  for (const panel of document.querySelectorAll(".tab-panel")) {
    panel.classList.toggle("active", panel.dataset.panel === name);
  }
}

async function requestTabSwitch(name) {
  const active = document.querySelector(".tab-button.active")?.dataset.tab;
  if (active === name) return;

  if (active === "basic" && basicEditing && basicDirty) {
    const shouldSave = window.confirm("基本信息有未保存修改，是否保存？\n确定保存后切换；取消将放弃修改并切换。");
    if (shouldSave) {
      const ok = await saveBasic();
      if (!ok) return;
    } else {
      fillBasicInfo(baselineBundle || currentBundle);
      setBasicEditing(false);
      setBasicDirty(false);
    }
  }

  if (hasEditingItems() && !window.confirm("当前有正在编辑的条目，切换后会放弃未保存内容。是否继续？")) {
    return;
  }
  cancelAllItemEdits();
  showTab(name);
}

function hasEditingItems() {
  return Boolean(document.querySelector(".config-item.editing"));
}

function cancelAllItemEdits() {
  for (const item of document.querySelectorAll(".config-item.editing")) {
    cancelItemEdit(item);
  }
}

function appendTodo(todo = {}) {
  for (const empty of refs.todoList.querySelectorAll(".empty-state")) empty.remove();
  const item = createTodoItem({ ...todo, priority: 3, status: "pending" }, { isNew: true, expanded: true, editing: true });
  refs.todoList.appendChild(item);
  item.scrollIntoView({ behavior: "smooth", block: "center" });
}

function appendCourse(course = {}) {
  for (const empty of refs.courseList.querySelectorAll(".empty-state")) empty.remove();
  const count = refs.courseList.querySelectorAll(".course-item").length;
  const item = createCourseItem(
    {
      local_id: makeLocalId("course"),
      day_of_week: "1",
      start_section: "1",
      end_section: "2",
      color: COURSE_COLORS[count % COURSE_COLORS.length],
      ...course,
    },
    { isNew: true, expanded: true, editing: true }
  );
  refs.courseList.appendChild(item);
  refreshScheduleFromDom();
  item.scrollIntoView({ behavior: "smooth", block: "center" });
}

function appendPush(push = {}) {
  for (const empty of refs.pushList.querySelectorAll(".empty-state")) empty.remove();
  const item = createPushItem(
    {
      push_id: makeLocalId("push"),
      type: "custom",
      frequency: "daily",
      repeat_count: 1,
      times: ["08:30"],
      ...push,
    },
    { isNew: true, expanded: true, editing: true }
  );
  refs.pushList.appendChild(item);
  item.scrollIntoView({ behavior: "smooth", block: "center" });
}

function addPushPreset(name) {
  const presets = {
    "竞赛提醒": {
      type: "interest",
      title: "竞赛提醒",
      content: "人工智能竞赛, 创新创业, 数学建模, Hackathon",
      frequency: "daily",
      times: ["09:00"],
    },
    "讲座推荐": {
      type: "interest",
      title: "讲座推荐",
      content: "AI 讲座, 科研分享, 学术报告, 行业交流",
      frequency: "weekly",
      weekdays: [1, 3, 5],
      times: ["18:30"],
    },
    "学院通知": {
      type: "interest",
      title: "学院通知",
      content: "学院通知, 课程安排, 考试安排, 评奖评优",
      frequency: "daily",
      times: ["08:30", "20:30"],
    },
    "DDL 催办": {
      type: "custom",
      title: "DDL 催办",
      content: "提醒我关注近期作业、报名截止和项目提交。",
      frequency: "daily",
      times: ["21:30"],
    },
  };
  appendPush(presets[name] || {});
  showToast(`已添加模板：${name}`);
}

async function bootstrap(userId) {
  if (DEMO_MODE) {
    currentUserId = DEMO_USER_ID;
    currentAccount = DEMO_PROFILE.name;
    pendingBindUserId = "";
    identitySource = "demo";
    demoStep = 0;
    currentBundle = normalizeBundle(createDemoBundle());
    baselineBundle = clone(currentBundle);
    hideLogin();
    fillUI(currentBundle);
    setSaveState("已同步", "saved");
    refs.apiState.textContent = "接口正常";
    refs.apiStateDetail.textContent = "已连接校园智能入口";
    refs.apiState.classList.remove("danger-text");
    return;
  }

  currentUserId = String(userId || "").trim();
  if (!currentUserId) {
    const storedAccount = normalizeAccount(localStorage.getItem(ACCOUNT_STORAGE_KEY) || "");
    showLogin(storedAccount);
    return;
  }

  pendingBindUserId = currentUserId;
  identitySource = "qq";
  try {
    const bundle = await fetchJson(`/api/user/bootstrap?user_id=${encodeURIComponent(currentUserId)}`);
    currentBundle = normalizeBundle(bundle);
    currentAccount = currentBundle.account || "";
    baselineBundle = clone(currentBundle);
    writeLocalDraft(currentBundle);
    fillUI(currentBundle);
    setSaveState("已同步", "saved");
    checkHealth();
  } catch (error) {
    const draft = readLocalDraft();
    if (draft) {
      currentBundle = normalizeBundle(draft);
      baselineBundle = clone(currentBundle);
      fillUI(currentBundle);
      setSaveState("本地草稿", "dirty");
      showToast(`后端暂不可用，已载入本地草稿：${error.message}`);
      return;
    }
    showFatal(`无法载入用户信息：${error.message}`);
  }
}

function showLogin(defaultAccount = "") {
  refs.loginOverlay.classList.remove("hidden");
  refs.accountInput.value = defaultAccount;
  refs.loginState.textContent = "";
  window.setTimeout(() => refs.accountInput.focus(), 0);
}

function hideLogin() {
  refs.loginOverlay.classList.add("hidden");
}

async function loginWithAccount(account) {
  const normalized = normalizeAccount(account);
  if (!normalized) {
    refs.loginState.textContent = "请先输入账号。";
    return false;
  }

  refs.accountLoginBtn.disabled = true;
  refs.loginState.textContent = "正在登录...";
  try {
    const bundle = await fetchJson("/api/account/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        account: normalized,
        bind_user_id: pendingBindUserId,
        legacy_user_id: "",
      }),
    });
    currentAccount = bundle.account || normalized;
    identitySource = pendingBindUserId ? "qq" : "account";
    currentBundle = normalizeBundle(bundle);
    baselineBundle = clone(currentBundle);
    writeLocalDraft(currentBundle);
    fillUI(currentBundle);
    hideLogin();
    setSaveState("已同步", "saved");
    checkHealth();
    showToast(`已进入账号：${currentAccount}`);
    return true;
  } catch (error) {
    refs.loginState.textContent = `登录失败：${error.message}`;
    return false;
  } finally {
    refs.accountLoginBtn.disabled = false;
  }
}

async function bindCurrentAccount() {
  const account = normalizeAccount(refs.accountBindInput.value);
  if (!account) {
    showToast("请输入要绑定的账号");
    return;
  }
  if (!currentUserId) {
    showToast("当前没有可绑定的用户标识");
    return;
  }
  pendingBindUserId = currentUserId;
  const ok = await loginWithAccount(account);
  if (ok) {
    showToast(`已绑定账号：${currentAccount}`);
  }
}

for (const control of document.querySelectorAll("[data-basic-editable]")) {
  control.addEventListener("input", () => {
    if (!basicEditing) return;
    setBasicDirty(true);
  });
  control.addEventListener("change", () => {
    if (!basicEditing) return;
    setBasicDirty(true);
  });
}

refs.basicEditBtn.addEventListener("click", () => {
  baselineBundle = clone(collectPayload({ allowIncomplete: true }));
  setBasicEditing(true);
  setBasicDirty(false);
});

refs.basicCancelBtn.addEventListener("click", () => {
  fillBasicInfo(baselineBundle || currentBundle);
  setBasicEditing(false);
  setBasicDirty(false);
});

refs.basicSaveBtn.addEventListener("click", saveBasic);
refs.chatSendBtn.addEventListener("click", () => sendChatMessage());
refs.briefBtn.addEventListener("click", generateDailyBrief);
refs.clearChatBtn.addEventListener("click", clearChatHistory);
refs.chatInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey) return;
  event.preventDefault();
  sendChatMessage();
});
for (const button of document.querySelectorAll(".quick-prompts button[data-prompt]")) {
  button.addEventListener("click", () => sendChatMessage(button.dataset.prompt));
}
for (const button of document.querySelectorAll(".preset-row button[data-push-preset]")) {
  button.addEventListener("click", () => addPushPreset(button.dataset.pushPreset));
}
refs.accountLoginBtn.addEventListener("click", () => loginWithAccount(refs.accountInput.value));
refs.accountInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  loginWithAccount(refs.accountInput.value);
});
refs.accountSwitchBtn.addEventListener("click", () => {
  if ((basicDirty || hasEditingItems()) && !window.confirm("当前有未保存内容，是否切换账号？")) return;
  pendingBindUserId = "";
  showLogin(currentAccount);
});
refs.accountBindBtn.addEventListener("click", bindCurrentAccount);

refs.addTodoBtn.addEventListener("click", () => appendTodo());
refs.addCourseBtn.addEventListener("click", () => appendCourse());
refs.addPushBtn.addEventListener("click", () => appendPush());

refs.importCourseBtn.addEventListener("click", () => refs.courseImportInput.click());
refs.courseImportInput.addEventListener("change", () => {
  const file = refs.courseImportInput.files?.[0];
  if (!file) return;
  showToast(`已选择 ${file.name}，后续可接入解析逻辑`);
  refs.courseImportInput.value = "";
});

for (const button of document.querySelectorAll(".tab-button")) {
  button.addEventListener("click", () => requestTabSwitch(button.dataset.tab));
}

refs.scheduleGrid.addEventListener("mousedown", (event) => {
  const slot = event.target.closest(".slot-cell");
  if (!slot) return;
  const day = Number(slot.dataset.day);
  const section = Number(slot.dataset.section);
  dragSelection = { day, start: section, current: section };
  paintScheduleSelection(day, section, section);
  event.preventDefault();
});

refs.scheduleGrid.addEventListener("mouseover", (event) => {
  if (!dragSelection) return;
  const slot = event.target.closest(".slot-cell");
  if (!slot) return;
  const day = Number(slot.dataset.day);
  const section = Number(slot.dataset.section);
  if (day !== dragSelection.day) return;
  dragSelection.current = section;
  paintScheduleSelection(day, dragSelection.start, section);
});

window.addEventListener("mouseup", () => {
  if (!dragSelection) return;
  const { day, start, current } = dragSelection;
  dragSelection = null;
  insertCourseFromSelection(day, start, current);
});

window.addEventListener("beforeunload", (event) => {
  if (!basicDirty && !hasEditingItems()) return;
  event.preventDefault();
  event.returnValue = "";
});

const queryUserId = PAGE_PARAMS.get("user_id");
bootstrap(queryUserId || "");
