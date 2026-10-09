import type { ReactNode } from "react";

/**
 * Reusable outline icons (Lucide-inspired): 24px viewBox, uniform
 * stroke width and round caps, colored via currentColor.
 */
type Props = { size?: number; className?: string };

function Svg({ children, size = 16, className }: Props & { children: ReactNode }) {
  return (
    <svg
      className={className ? `ico ${className}` : "ico"}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const Layers = (p: Props) => (
  <Svg {...p}>
    <path d="m12 2 9 4.5-9 4.5-9-4.5L12 2Z" />
    <path d="m3 11.5 9 4.5 9-4.5" />
    <path d="m3 16.5 9 4.5 9-4.5" />
  </Svg>
);

export const Pulse = (p: Props) => (
  <Svg {...p}>
    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
  </Svg>
);

export const FileCode = (p: Props) => (
  <Svg {...p}>
    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
    <path d="M14 2v4a2 2 0 0 0 2 2h4" />
    <path d="m10 12-2 2.5L10 17" />
    <path d="m14 12 2 2.5-2 2.5" />
  </Svg>
);

export const Mail = (p: Props) => (
  <Svg {...p}>
    <rect x="2" y="4" width="20" height="16" rx="2" />
    <path d="m22 7-10 6L2 7" />
  </Svg>
);

export const Sliders = (p: Props) => (
  <Svg {...p}>
    <path d="M21 7h-8" />
    <path d="M9 7H3" />
    <path d="M15 17H3" />
    <path d="M21 17h-6" />
    <circle cx="11" cy="7" r="2" />
    <circle cx="17" cy="17" r="2" />
  </Svg>
);

export const Terminal = (p: Props) => (
  <Svg {...p}>
    <path d="m4 17 6-6-6-6" />
    <path d="M12 19h8" />
  </Svg>
);

export const Folder = (p: Props) => (
  <Svg {...p}>
    <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
  </Svg>
);

export const FolderPlus = (p: Props) => (
  <Svg {...p}>
    <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
    <path d="M12 10v6" />
    <path d="M9 13h6" />
  </Svg>
);

export const File = (p: Props) => (
  <Svg {...p}>
    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
    <path d="M14 2v4a2 2 0 0 0 2 2h4" />
  </Svg>
);

export const GitBranch = (p: Props) => (
  <Svg {...p}>
    <path d="M6 3v12" />
    <circle cx="18" cy="6" r="3" />
    <circle cx="6" cy="18" r="3" />
    <path d="M18 9a9 9 0 0 1-9 9" />
  </Svg>
);

export const Globe = (p: Props) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="10" />
    <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
    <path d="M2 12h20" />
  </Svg>
);

export const Clock = (p: Props) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="10" />
    <path d="M12 6v6l4 2" />
  </Svg>
);

export const Users = (p: Props) => (
  <Svg {...p}>
    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </Svg>
);

export const Trash = (p: Props) => (
  <Svg {...p}>
    <path d="M3 6h18" />
    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
    <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    <path d="M10 11v6" />
    <path d="M14 11v6" />
  </Svg>
);

export const Play = (p: Props) => (
  <Svg {...p}>
    <path d="m6 4 14 8-14 8V4Z" />
  </Svg>
);

export const Square = (p: Props) => (
  <Svg {...p}>
    <rect x="6" y="6" width="12" height="12" rx="1.5" />
  </Svg>
);

export const Restart = (p: Props) => (
  <Svg {...p}>
    <path d="M21 12a9 9 0 1 1-2.64-6.36L21 8" />
    <path d="M21 3v5h-5" />
  </Svg>
);

export const Refresh = (p: Props) => (
  <Svg {...p}>
    <path d="M3 12a9 9 0 0 1 15.36-6.36L21 8" />
    <path d="M21 3v5h-5" />
    <path d="M21 12a9 9 0 0 1-15.36 6.36L3 16" />
    <path d="M3 21v-5h5" />
  </Svg>
);

export const ChevronRight = (p: Props) => (
  <Svg {...p}>
    <path d="m9 18 6-6-6-6" />
  </Svg>
);

export const ChevronUp = (p: Props) => (
  <Svg {...p}>
    <path d="m18 15-6-6-6 6" />
  </Svg>
);

export const Search = (p: Props) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </Svg>
);

export const X = (p: Props) => (
  <Svg {...p}>
    <path d="M18 6 6 18" />
    <path d="m6 6 12 12" />
  </Svg>
);

export const LogOut = (p: Props) => (
  <Svg {...p}>
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
    <path d="m16 17 5-5-5-5" />
    <path d="M21 12H9" />
  </Svg>
);

export const PanelLeft = (p: Props) => (
  <Svg {...p}>
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <path d="M9 3v18" />
  </Svg>
);

export const Plus = (p: Props) => (
  <Svg {...p}>
    <path d="M5 12h14" />
    <path d="M12 5v14" />
  </Svg>
);

export const Upload = (p: Props) => (
  <Svg {...p}>
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <path d="m17 8-5-5-5 5" />
    <path d="M12 3v12" />
  </Svg>
);

export const AlertTriangle = (p: Props) => (
  <Svg {...p}>
    <path d="m21.73 18-8-14a2 2 0 0 0-3.46 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
    <path d="M12 9v4" />
    <path d="M12 17h.01" />
  </Svg>
);

export const Check = (p: Props) => (
  <Svg {...p}>
    <path d="M20 6 9 17l-5-5" />
  </Svg>
);

export const Info = (p: Props) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="10" />
    <path d="M12 16v-4" />
    <path d="M12 8h.01" />
  </Svg>
);

export const Server = (p: Props) => (
  <Svg {...p}>
    <rect x="2" y="3" width="20" height="7" rx="2" />
    <rect x="2" y="14" width="20" height="7" rx="2" />
    <path d="M6 6.5h.01" />
    <path d="M6 17.5h.01" />
  </Svg>
);

export const Spinner = ({ size = 14, className }: Props) => (
  <svg
    className={`ico spin${className ? ` ${className}` : ""}`}
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.25"
    strokeLinecap="round"
    aria-hidden="true"
  >
    <path d="M21 12a9 9 0 1 1-6.22-8.56" />
  </svg>
);