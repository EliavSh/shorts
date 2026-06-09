export function isMobileUA(): boolean {
  if (typeof navigator === "undefined") return false;
  return /iPhone|iPad|iPod|Android|Mobile|webOS|BlackBerry/i.test(navigator.userAgent);
}

export function isMobileViewport(breakpoint = 1024): boolean {
  if (typeof window === "undefined") return false;
  return window.innerWidth < breakpoint;
}

export function isMobile(): boolean {
  return isMobileUA() || isMobileViewport();
}
