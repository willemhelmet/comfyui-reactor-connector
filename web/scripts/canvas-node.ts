import { app } from '../../scripts/app.js';

/**
 * Find the graph node that owns a live session.
 * @param nodeId - The node id sent with the session invitation.
 * @returns The node on the current graph, or null when it cannot be resolved.
 */
export function findCanvasNode(nodeId: string): ReturnType<typeof app.rootGraph.getNodeById> {
  if (!app.isGraphReady) return null;
  const graph = app.rootGraph;
  const direct = graph.getNodeById(nodeId);
  if (direct) return direct;
  if (!/^\d{1,16}$/.test(nodeId)) return null;
  const numeric = Number(nodeId);
  if (!Number.isSafeInteger(numeric)) return null;
  return graph.getNodeById(numeric);
}
