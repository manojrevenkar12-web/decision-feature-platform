/** Motion constants (seconds). One orchestrated reveal on load: the budget tracks fill in order.
 * Everything else changes only when the reader acts (switching the seed set). */
export const motion = {
  base: 0.6,
  stagger: 0.16,
  quick: 0.2,
  ease: [0.22, 0.9, 0.3, 1] as const,
};
