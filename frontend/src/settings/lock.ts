/**
 * Authentication & Access Bridge for Protected Settings areas.
 * Authentication is performed persistently at the system Auth Gateway.
 */

export interface Lockable {
  id: string;
  root: () => HTMLElement | null;
  onUnlock: () => void | Promise<void>;
  onLock: () => void;
}

const lockables = new Map<string, Lockable>();

export function isUnlocked(_id?: string): boolean {
  return true;
}

export function lockAll(): void {
  // Session is maintained persistently. No-op to avoid clearing token or locking.
}

export function registerLockable(l: Lockable): void {
  lockables.set(l.id, l);
  l.root()?.classList.remove("locked");
}

export async function enterLockable(id: string): Promise<void> {
  const l = lockables.get(id);
  if (l) {
    l.root()?.classList.remove("locked");
    await l.onUnlock();
  }
}
