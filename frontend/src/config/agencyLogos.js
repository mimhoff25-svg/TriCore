const AGENCY_LOGOS = [
  {
    id: "travis-county",
    label: "Travis Co",
    src: "/logos/travis-county.svg",
    match: ["travis county", "gatrrs"],
  },
  {
    id: "austin-fire",
    label: "Austin Fire",
    src: "/logos/austin-fire.svg",
    match: ["austin fire", "austin fire & ems", "afd"],
  },
  {
    id: "austin-police",
    label: "APD",
    src: "/logos/apd.jpg",
    match: ["austin police", "austin police department", "apd", "law dispatch", "law tac"],
  },
  {
    id: "austin-ems",
    label: "Austin EMS",
    src: "/logos/austin-ems.svg",
    match: ["austin ems", "ems dispatch"],
  },
  {
    id: "austin-utilities",
    label: "Austin Util",
    src: "/logos/austin-utilities.svg",
    match: ["austin water", "wastewater", "utilities"],
  },
];

function getInitials(text) {
  if (!text) return "SCAN";
  return text
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || "")
    .join("") || "SCAN";
}

export function getAgencyLogo(channel) {
  const system = String(channel?.system || "");
  const department = String(channel?.department || "");
  const name = String(channel?.name || "");
  const search = `${system} ${department} ${name}`.toLowerCase();

  const matched = AGENCY_LOGOS.find((entry) =>
    entry.match.some((needle) => search.includes(needle))
  );

  if (matched) {
    return matched;
  }

  return {
    id: "fallback",
    label: getInitials(department || system || name),
    src: null,
  };
}
