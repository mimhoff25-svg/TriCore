import { ChevronDown, ChevronRight, FolderOpen, Lock, Radio, RadioTower, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

const AGENCY_ALIASES = {
  TCSO: "Travis County Sheriff's Office",
  AFD: "Austin Fire Department",
  TCEMS: "Austin/Travis County EMS",
  AISD: "Austin Independent School District",
  APD: "Austin Police Department",
};

const PINNED_SYSTEM_ORDER = [
  "Travis County Sheriff's Office",
  "Austin Fire Department",
  "Austin/Travis County EMS",
  "NOAA Weather",
];

function slugify(value) {
  return String(value || "item")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "item";
}

function formatMHz(frequencyHz) {
  const parsed = Number(frequencyHz);
  if (!Number.isFinite(parsed) || parsed <= 0) return "--.----";
  return (parsed / 1_000_000).toFixed(4);
}

function prettyLabel(value) {
  const text = String(value || "").trim();
  if (!text) return "Other";
  if (text.includes(" / ")) return text;
  if (/[A-Z]{2,}/.test(text)) return text.replace(/_/g, " ");
  return text
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function sortWeight(name) {
  const index = PINNED_SYSTEM_ORDER.findIndex((item) => item.toLowerCase() === String(name || "").toLowerCase());
  return index === -1 ? PINNED_SYSTEM_ORDER.length : index;
}

function talkgroupSystemName(talkgroup) {
  const alphaTag = String(talkgroup?.alpha_tag || "").trim().toUpperCase();
  const prefix = alphaTag.split(/[\s-]+/, 1)[0];
  if (AGENCY_ALIASES[prefix]) {
    return AGENCY_ALIASES[prefix];
  }

  const tag = String(talkgroup?.tag || talkgroup?.category || "").trim();
  if (tag.includes(" / ")) {
    return tag.split(" / ", 1)[0].trim();
  }
  return prettyLabel(tag || "GATRRS");
}

function talkgroupCategoryName(talkgroup) {
  const tag = String(talkgroup?.tag || talkgroup?.category || "").trim();
  if (tag.includes(" / ")) {
    return prettyLabel(tag.split(" / ", 2)[1]);
  }
  return prettyLabel(talkgroup?.category || talkgroup?.service_type || "Talkgroups");
}

function channelSystemName(channel) {
  return prettyLabel(channel?.system_name || "Local");
}

function channelCategoryName(channel) {
  return prettyLabel(channel?.category || channel?.service_type || "Other");
}

function ensureSystemNode(map, name) {
  const key = slugify(name);
  if (!map.has(key)) {
    map.set(key, {
      id: `system:${key}`,
      name,
      nodeType: "system",
      childMap: new Map(),
      sortWeight: sortWeight(name),
    });
  }
  return map.get(key);
}

function ensureCategoryNode(systemNode, name, sourceKind) {
  const key = slugify(`${sourceKind}-${name}`);
  if (!systemNode.childMap.has(key)) {
    systemNode.childMap.set(key, {
      id: `${systemNode.id}:category:${key}`,
      name,
      nodeType: "category",
      sourceKind,
      childMap: new Map(),
    });
  }
  return systemNode.childMap.get(key);
}

function makeChannelLeaf(channel, activeChannel) {
  const monitorable = !channel.unavailable && !channel.encrypted;
  const enabled = Boolean(channel.scan_enabled);
  return {
    id: `channel:${channel.id}`,
    nodeType: "channel",
    name: channel.name,
    subtitle: `${formatMHz(channel.frequency_hz)} MHz`,
    badge: "SCAN",
    selectable: monitorable,
    toggleable: monitorable,
    enabled: monitorable ? enabled : false,
    mixed: false,
    active: activeChannel?.id === channel.id,
    muted: !monitorable,
    channelIds: monitorable ? [channel.id] : [],
    talkgroupDecimals: [],
    totalCount: monitorable ? 1 : 0,
    enabledCount: monitorable && enabled ? 1 : 0,
    item: channel,
    children: [],
  };
}

function makeTalkgroupLeaf(talkgroup, selectedTalkgroup) {
  const monitorable = !talkgroup.encrypted;
  const enabled = Boolean(talkgroup.scan_enabled);
  return {
    id: `talkgroup:${talkgroup.decimal}`,
    nodeType: "talkgroup",
    name: talkgroup.alpha_tag,
    subtitle: `TG ${talkgroup.decimal} - ${talkgroup.description || prettyLabel(talkgroup.service_type)}`,
    badge: "P25",
    selectable: monitorable,
    toggleable: monitorable,
    enabled: monitorable ? enabled : false,
    mixed: false,
    active: Number(selectedTalkgroup?.decimal || 0) === Number(talkgroup.decimal || 0),
    muted: !monitorable,
    channelIds: [],
    talkgroupDecimals: monitorable ? [Number(talkgroup.decimal)] : [],
    totalCount: monitorable ? 1 : 0,
    enabledCount: monitorable && enabled ? 1 : 0,
    item: talkgroup,
    children: [],
  };
}

function finalizeNode(node) {
  if (node.nodeType === "channel" || node.nodeType === "talkgroup") {
    return node;
  }

  const children = [...node.childMap.values()]
    .map(finalizeNode)
    .sort((left, right) => {
      if (left.active !== right.active) return left.active ? -1 : 1;
      if (left.nodeType === "category" && right.nodeType === "category") {
        return left.name.localeCompare(right.name);
      }
      if (left.nodeType === "channel" && right.nodeType === "talkgroup") return -1;
      if (left.nodeType === "talkgroup" && right.nodeType === "channel") return 1;
      return left.name.localeCompare(right.name);
    });
  const channelIds = children.flatMap((child) => child.channelIds || []);
  const talkgroupDecimals = children.flatMap((child) => child.talkgroupDecimals || []);
  const enabledCount = children.reduce((total, child) => total + Number(child.enabledCount || 0), 0);
  const totalCount = children.reduce((total, child) => total + Number(child.totalCount || 0), 0);
  const active = children.some((child) => child.active);
  return {
    id: node.id,
    name: node.name,
    nodeType: node.nodeType,
    sourceKind: node.sourceKind,
    children,
    channelIds,
    talkgroupDecimals,
    enabledCount,
    totalCount,
    enabled: totalCount > 0 && enabledCount === totalCount,
    mixed: enabledCount > 0 && enabledCount < totalCount,
    active,
    muted: totalCount === 0,
  };
}

function buildScanTree(channels, talkgroups, activeChannel, selectedTalkgroup) {
  const systems = new Map();

  for (const channel of channels.filter((item) => item.modulation !== "p25_placeholder")) {
    const systemNode = ensureSystemNode(systems, channelSystemName(channel));
    const categoryNode = ensureCategoryNode(systemNode, channelCategoryName(channel), "channel");
    categoryNode.childMap.set(channel.id, makeChannelLeaf(channel, activeChannel));
  }

  for (const talkgroup of talkgroups) {
    const systemNode = ensureSystemNode(systems, talkgroupSystemName(talkgroup));
    const categoryNode = ensureCategoryNode(systemNode, talkgroupCategoryName(talkgroup), "talkgroup");
    categoryNode.childMap.set(String(talkgroup.decimal), makeTalkgroupLeaf(talkgroup, selectedTalkgroup));
  }

  return [...systems.values()]
    .map(finalizeNode)
    .sort((left, right) => {
      if (left.active !== right.active) return left.active ? -1 : 1;
      if ((left.sortWeight || sortWeight(left.name)) !== (right.sortWeight || sortWeight(right.name))) {
        return (left.sortWeight || sortWeight(left.name)) - (right.sortWeight || sortWeight(right.name));
      }
      return left.name.localeCompare(right.name);
    });
}

function filterTree(nodes, query) {
  if (!query) return nodes;
  const lowered = query.toLowerCase();

  function matches(node) {
    const haystack = [node.name, node.subtitle, node.item?.description, node.item?.tag]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(lowered);
  }

  function visit(node) {
    if (!node.children?.length) {
      return matches(node) ? node : null;
    }
    const children = node.children.map(visit).filter(Boolean);
    if (children.length || matches(node)) {
      const enabledCount = children.reduce((total, child) => total + Number(child.enabledCount || 0), 0);
      const totalCount = children.reduce((total, child) => total + Number(child.totalCount || 0), 0);
      return {
        ...node,
        children,
        channelIds: children.flatMap((child) => child.channelIds || []),
        talkgroupDecimals: children.flatMap((child) => child.talkgroupDecimals || []),
        enabledCount,
        totalCount,
        enabled: totalCount > 0 && enabledCount === totalCount,
        mixed: enabledCount > 0 && enabledCount < totalCount,
        active: children.some((child) => child.active) || node.active,
      };
    }
    return null;
  }

  return nodes.map(visit).filter(Boolean);
}

function ScanCheckbox({ checked, indeterminate, disabled, label, onChange }) {
  const inputRef = useRef(null);

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.indeterminate = Boolean(indeterminate);
    }
  }, [indeterminate]);

  return (
    <input
      ref={inputRef}
      type="checkbox"
      checked={checked}
      disabled={disabled}
      aria-label={label}
      onChange={(event) => onChange?.(event.target.checked)}
      className="h-4 w-4 rounded border-white/20 bg-[#0b111a] accent-triCoreGreen"
    />
  );
}

function NodeRow({
  node,
  depth,
  query,
  expanded,
  setExpanded,
  onTune,
  onSelectTalkgroup,
  onSetScanEnabled,
}) {
  const hasChildren = Boolean(node.children?.length);
  const defaultExpanded = Boolean(query) || node.active;
  const isExpanded = hasChildren && (expanded[node.id] ?? defaultExpanded);
  const rowPadding = 12 + (depth * 14);
  const checkboxDisabled = node.totalCount === 0;

  function toggleOpen() {
    if (!hasChildren) return;
    setExpanded((current) => ({
      ...current,
      [node.id]: !(current[node.id] ?? defaultExpanded),
    }));
  }

  function toggleScan(enabled) {
    onSetScanEnabled?.(node, enabled);
  }

  function selectLeaf() {
    if (!node.selectable) {
      return;
    }
    if (node.nodeType === "talkgroup") {
      onSelectTalkgroup?.(node.item);
      return;
    }
    onTune?.(node.item.id);
  }

  return (
    <div>
      <div
        className={`flex items-center gap-2 border-b border-white/5 py-2 pr-3 ${node.active ? "bg-triCoreBlue/10" : "bg-transparent"}`}
        style={{ paddingLeft: `${rowPadding}px` }}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={toggleOpen}
            className="flex h-5 w-5 items-center justify-center rounded text-slate-400 hover:bg-white/5 hover:text-white"
            aria-label={isExpanded ? `Collapse ${node.name}` : `Expand ${node.name}`}
          >
            {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
        ) : (
          <span className="block h-5 w-5" />
        )}

        <ScanCheckbox
          checked={Boolean(node.enabled)}
          indeterminate={Boolean(node.mixed)}
          disabled={checkboxDisabled}
          label={`Scan ${node.name}`}
          onChange={toggleScan}
        />

        <button
          type="button"
          disabled={hasChildren ? false : !node.selectable}
          onClick={hasChildren ? toggleOpen : selectLeaf}
          className={`flex min-w-0 flex-1 items-center gap-2 text-left ${!hasChildren && !node.selectable ? "cursor-not-allowed opacity-60" : ""}`}
        >
          {hasChildren ? (
            <FolderOpen className={`h-4 w-4 shrink-0 ${node.active ? "text-triCoreBlue" : "text-slate-500"}`} />
          ) : node.nodeType === "talkgroup" ? (
            <RadioTower className={`h-4 w-4 shrink-0 ${node.active ? "text-triCoreBlue" : "text-slate-500"}`} />
          ) : (
            <Radio className={`h-4 w-4 shrink-0 ${node.active ? "text-triCoreGreen" : "text-slate-500"}`} />
          )}

          <div className="min-w-0 flex-1">
            <div className={`truncate text-sm font-semibold ${node.active ? "text-white" : "text-slate-200"}`}>{node.name}</div>
            <div className="truncate text-[11px] text-slate-500">
              {hasChildren
                ? `${node.enabledCount}/${node.totalCount} scan enabled`
                : node.subtitle}
            </div>
          </div>
        </button>

        {!hasChildren && node.muted ? (
          <span className="flex shrink-0 items-center gap-1 rounded border border-red-400/30 px-2 py-0.5 text-[10px] font-semibold text-red-300">
            <Lock className="h-3 w-3" />
            LOCK
          </span>
        ) : !hasChildren ? (
          <span className={`shrink-0 rounded border px-2 py-0.5 text-[10px] font-semibold ${node.nodeType === "talkgroup" ? "border-triCoreBlue/30 text-triCoreBlue" : "border-triCoreGreen/30 text-triCoreGreen"}`}>
            {node.badge}
          </span>
        ) : null}
      </div>

      {hasChildren && isExpanded && (
        <div>
          {node.children.map((child) => (
            <NodeRow
              key={child.id}
              node={child}
              depth={depth + 1}
              query={query}
              expanded={expanded}
              setExpanded={setExpanded}
              onTune={onTune}
              onSelectTalkgroup={onSelectTalkgroup}
              onSetScanEnabled={onSetScanEnabled}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function ScanFoldersPanel({
  channels = [],
  talkgroups = [],
  activeChannel,
  selectedTalkgroup,
  onTune,
  onSelectTalkgroup,
  onSetScanEnabled,
}) {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState({});

  const tree = useMemo(
    () => buildScanTree(channels, talkgroups, activeChannel, selectedTalkgroup),
    [channels, talkgroups, activeChannel, selectedTalkgroup],
  );

  const filteredTree = useMemo(
    () => filterTree(tree, query.trim().toLowerCase()),
    [tree, query],
  );

  const summary = useMemo(() => {
    return {
      enabled: tree.reduce((total, node) => total + Number(node.enabledCount || 0), 0),
      total: tree.reduce((total, node) => total + Number(node.totalCount || 0), 0),
    };
  }, [tree]);

  return (
    <aside className="rounded-lg border border-white/10 bg-[#101720]">
      <div className="border-b border-white/10 p-4">
        <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
          <FolderOpen className="h-4 w-4 text-triCoreBlue" />
          Scan Folders
        </div>
        <div className="mt-1 text-xs text-slate-500">
          Top folders are agencies or systems. Check or uncheck any folder, category, or single channel.
        </div>
        <div className="mt-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">
          {summary.enabled}/{summary.total} items enabled for scan
        </div>
        <div className="mt-3 flex items-center gap-2 rounded-md border border-white/10 bg-black/20 px-2 py-1.5">
          <Search className="h-4 w-4 text-slate-500" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter folders, channels, talkgroups"
            className="w-full bg-transparent text-sm text-white placeholder:text-slate-500 focus:outline-none"
          />
        </div>
      </div>

      <div className="max-h-[48vh] overflow-y-auto">
        {filteredTree.map((node) => (
          <NodeRow
            key={node.id}
            node={node}
            depth={0}
            query={query}
            expanded={expanded}
            setExpanded={setExpanded}
            onTune={onTune}
            onSelectTalkgroup={onSelectTalkgroup}
            onSetScanEnabled={onSetScanEnabled}
          />
        ))}
        {filteredTree.length === 0 && (
          <div className="p-4 text-sm text-slate-500">No folders matched that filter.</div>
        )}
      </div>
    </aside>
  );
}
