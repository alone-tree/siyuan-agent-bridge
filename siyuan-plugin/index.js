const {Dialog, Plugin, Setting, showMessage} = require("siyuan");

const PLUGIN_NAME = "siyuan-bridge";
const CONFIG_PATH = `/data/plugins/${PLUGIN_NAME}/bridge/config.local.json`;
const DEFAULT_CONFIG = {
  profiles: [{name: "当前工作空间", token: ""}],
  language: "zh-CN",
};

class SiyuanBridgePlugin extends Plugin {
  onload() {
    const openButton = document.createElement("button");
    openButton.className = "b3-button";
    openButton.textContent = "打开设置";
    openButton.addEventListener("click", () => this.openSettings());

    this.setting = new Setting({
      confirmCallback: () => this.openSettings(),
    });
    this.setting.addItem({
      title: "思源桥配置",
      description: "配置 Python MCP Bridge、工作空间 Token，并生成 MCP JSON。",
      actionElement: openButton,
    });

    this.addCommand({
      langKey: "openSiyuanBridgeSettings",
      langText: "打开思源桥设置",
      hotkey: "",
      callback: () => this.openSettings(),
    });

    ensureDefaultBridgeConfig().catch((error) => {
      console.warn("Siyuan Bridge config init failed", error);
    });
  }

  onLayoutReady() {
    this.addTopBar({
      icon: "iconSettings",
      title: "思源桥",
      position: "right",
      callback: () => this.openSettings(),
    });
  }

  async openSettings() {
    const context = await getPluginContext();
    const config = await loadBridgeConfig(context);
    const dialog = new Dialog({
      title: "思源桥设置",
      content: renderSettings(config, context),
      width: "760px",
      height: "720px",
    });

    bindSettings(dialog.element, config, context);
  }
}

async function getPluginContext() {
  const systemConf = await getSystemConf();
  const workspaceDir = systemConf.workspaceDir || window.siyuan?.config?.system?.workspaceDir || "";
  const guessedPluginDir = workspaceDir ? joinPath(workspaceDir, "data", "plugins", PLUGIN_NAME) : "";
  const guessedBridgeDir = guessedPluginDir ? joinPath(guessedPluginDir, "bridge") : "";
  const guessedRunMcp = guessedBridgeDir
    ? joinPath(guessedBridgeDir, "scripts", "run_mcp.py")
    : "";
  return {
    currentWorkspaceName: workspaceDir ? workspaceDir.split(/[\\/]/).filter(Boolean).pop() || "当前工作空间" : "当前工作空间",
    currentToken: systemConf.token || "",
    pluginDir: guessedPluginDir,
    bridgeDir: guessedBridgeDir,
    runMcpPath: guessedRunMcp,
    pythonCommand: "python",
    serverName: "siyuan-bridge",
  };
}

async function loadBridgeConfig(context) {
  const existing = await readBridgeConfig();
  const config = existing.config || JSON.parse(JSON.stringify(DEFAULT_CONFIG));
  return applyCurrentWorkspaceDefaults(config, context);
}

async function readBridgeConfig() {
  try {
    const text = await getFile(CONFIG_PATH);
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object" && Array.isArray(parsed.profiles)) {
      return {config: normalizeConfig(parsed), exists: true};
    }
  } catch (_error) {
    // Missing config is normal on first run.
  }
  return {config: null, exists: false};
}

function normalizeConfig(config) {
  const profiles = Array.isArray(config.profiles) && config.profiles.length
    ? config.profiles
    : DEFAULT_CONFIG.profiles;
  return {
    profiles: profiles.map((profile, index) => ({
      name: String(profile?.name || (index === 0 ? "当前工作空间" : `工作空间 ${index + 1}`)),
      token: String(profile?.token || ""),
    })),
    language: String(config.language || "zh-CN"),
  };
}

function applyCurrentWorkspaceDefaults(config, context) {
  const normalized = normalizeConfig(config);
  if (!normalized.profiles.length) {
    normalized.profiles.push({name: context.currentWorkspaceName || "当前工作空间", token: context.currentToken || ""});
  }
  if (!normalized.profiles[0].name || normalized.profiles[0].name === "当前工作空间") {
    normalized.profiles[0].name = context.currentWorkspaceName || "当前工作空间";
  }
  if (!normalized.profiles[0].token && context.currentToken) {
    normalized.profiles[0].token = context.currentToken;
  }
  return normalized;
}

async function ensureDefaultBridgeConfig() {
  const context = await getPluginContext();
  if (!context.currentToken) {
    return;
  }
  const existing = await readBridgeConfig();
  const existingFirstToken = existing.config?.profiles?.[0]?.token || "";
  const config = applyCurrentWorkspaceDefaults(existing.config || DEFAULT_CONFIG, context);
  if (!existing.exists || !existingFirstToken) {
    await saveBridgeConfig(config);
  }
}

function renderSettings(config, context) {
  const escapedConfig = escapeAttr(JSON.stringify(config));
  return `
    <div class="siyuan-bridge" data-config="${escapedConfig}">
      <div class="siyuan-bridge__section">
        <label class="siyuan-bridge__field">
          <span class="siyuan-bridge__label">Python 命令</span>
          <input class="b3-text-field fn__block" data-field="pythonCommand" value="${escapeAttr(context.pythonCommand)}" placeholder="python" />
        </label>
        <label class="siyuan-bridge__field">
          <span class="siyuan-bridge__label">MCP Server 名称</span>
          <input class="b3-text-field fn__block" data-field="serverName" value="${escapeAttr(context.serverName)}" placeholder="siyuan-bridge" />
        </label>
      </div>

      <div class="siyuan-bridge__section">
        <label class="siyuan-bridge__field">
          <span class="siyuan-bridge__label">插件目录</span>
          <input class="b3-text-field fn__block" data-field="pluginDir" value="${escapeAttr(context.pluginDir)}" />
        </label>
        <label class="siyuan-bridge__field">
          <span class="siyuan-bridge__label">Bridge 目录</span>
          <input class="b3-text-field fn__block" data-field="bridgeDir" value="${escapeAttr(context.bridgeDir)}" />
        </label>
        <label class="siyuan-bridge__field">
          <span class="siyuan-bridge__label">MCP 启动脚本</span>
          <input class="b3-text-field fn__block" data-field="runMcpPath" value="${escapeAttr(context.runMcpPath)}" />
        </label>
      </div>

      <div class="siyuan-bridge__section">
        <div class="siyuan-bridge__header">
          <span>工作空间 Profiles</span>
          <button class="b3-button b3-button--outline" data-action="add-profile">添加工作空间</button>
        </div>
        <div data-profiles>${renderProfiles(config.profiles)}</div>
      </div>

      <div class="siyuan-bridge__section">
        <div class="siyuan-bridge__header">
          <span>MCP JSON</span>
          <button class="b3-button" data-action="copy-json">复制 JSON</button>
        </div>
        <textarea class="b3-text-field siyuan-bridge__json" data-field="mcpJson" readonly></textarea>
      </div>

      <div class="siyuan-bridge__actions">
        <button class="b3-button" data-action="save">保存配置</button>
        <button class="b3-button b3-button--outline" data-action="refresh-json">刷新 JSON</button>
      </div>
    </div>
  `;
}

function renderProfiles(profiles) {
  return profiles.map((profile, index) => `
    <div class="siyuan-bridge__profile" data-profile-index="${index}">
      <input class="b3-text-field" data-profile-field="name" value="${escapeAttr(profile.name)}" placeholder="${index === 0 ? "当前工作空间" : "工作空间名称"}" />
      <input class="b3-text-field" data-profile-field="token" value="${escapeAttr(profile.token)}" placeholder="API Token" type="text" />
      <button class="b3-button b3-button--outline" data-action="remove-profile" ${index === 0 ? "disabled" : ""}>删除</button>
    </div>
  `).join("");
}

function bindSettings(root, config, context) {
  const container = root.querySelector(".siyuan-bridge");
  const state = {
    config: normalizeConfig(config),
    context: {...context},
  };

  const refreshProfiles = () => {
    container.querySelector("[data-profiles]").innerHTML = renderProfiles(state.config.profiles);
    refreshJson();
  };

  const refreshJson = () => {
    readContext(container, state);
    const textarea = container.querySelector("[data-field='mcpJson']");
    textarea.value = JSON.stringify(buildMcpConfig(state.context), null, 2);
  };

  container.addEventListener("input", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) {
      return;
    }
    const profileEl = target.closest("[data-profile-index]");
    if (profileEl) {
      const index = Number(profileEl.getAttribute("data-profile-index"));
      const field = target.getAttribute("data-profile-field");
      if (field === "name" || field === "token") {
        state.config.profiles[index][field] = target.value;
      }
    }
    refreshJson();
  });

  container.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const action = target.getAttribute("data-action");
    if (!action) {
      return;
    }
    if (action === "add-profile") {
      state.config.profiles.push({name: `工作空间 ${state.config.profiles.length + 1}`, token: ""});
      refreshProfiles();
    }
    if (action === "remove-profile") {
      const profileEl = target.closest("[data-profile-index]");
      const index = Number(profileEl?.getAttribute("data-profile-index"));
      if (index > 0) {
        state.config.profiles.splice(index, 1);
        refreshProfiles();
      }
    }
    if (action === "refresh-json") {
      refreshJson();
    }
    if (action === "copy-json") {
      refreshJson();
      await navigator.clipboard.writeText(container.querySelector("[data-field='mcpJson']").value);
      showMessage("MCP JSON 已复制");
    }
    if (action === "save") {
      readContext(container, state);
      await saveBridgeConfig(state.config);
      refreshJson();
      showMessage("思源桥配置已保存");
    }
  });

  refreshJson();
}

function readContext(container, state) {
  for (const key of ["pythonCommand", "serverName", "pluginDir", "bridgeDir", "runMcpPath"]) {
    const input = container.querySelector(`[data-field='${key}']`);
    if (input instanceof HTMLInputElement) {
      state.context[key] = input.value.trim();
    }
  }
}

async function saveBridgeConfig(config) {
  const normalized = normalizeConfig(config);
  await putFile(CONFIG_PATH, JSON.stringify(normalized, null, 2) + "\n");
}

function buildMcpConfig(context) {
  return {
    mcpServers: {
      [context.serverName || "siyuan-bridge"]: {
        command: context.pythonCommand || "python",
        args: [context.runMcpPath || ""],
        env: {
          PYTHONUTF8: "1",
        },
      },
    },
  };
}

async function getFile(path) {
  const response = await fetch("/api/file/getFile", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({path}),
  });
  return response.text();
}

async function getSystemConf() {
  try {
    const response = await fetch("/api/system/getConf", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: "{}",
    });
    const envelope = await response.json();
    const conf = envelope?.data?.conf || {};
    return {
      token: String(conf?.api?.token || ""),
      workspaceDir: String(conf?.system?.workspaceDir || ""),
    };
  } catch (_error) {
    return {token: "", workspaceDir: ""};
  }
}

async function putFile(path, content) {
  const formData = new FormData();
  formData.append("path", path);
  formData.append("file", new Blob([content], {type: "application/json"}), "config.local.json");
  const response = await fetch("/api/file/putFile", {
    method: "POST",
    body: formData,
  });
  const envelope = await response.json();
  if (envelope.code !== 0) {
    throw new Error(envelope.msg || "写入配置失败");
  }
}

function joinPath(...parts) {
  const separator = navigator.platform.toLowerCase().includes("win") ? "\\" : "/";
  return parts
    .filter(Boolean)
    .join(separator)
    .replace(/[\\/]+/g, separator);
}

function escapeAttr(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

module.exports = SiyuanBridgePlugin;
module.exports.default = SiyuanBridgePlugin;
