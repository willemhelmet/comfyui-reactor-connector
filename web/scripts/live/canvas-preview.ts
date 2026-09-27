import { element } from '#web/dom.ts';
import { findCanvasNode } from '#web/canvas-node.ts';
import { message, releaseText, setTextAttribute } from '#web/localization.ts';

const widgetName = 'reactorLivePreview';
const previewMinHeight = 180;

type FoundNode = NonNullable<ReturnType<typeof findCanvasNode>>;
type NodeWidget = Parameters<FoundNode['ensureWidgetRemoved']>[0];
type PreviewOptions = {
  serialize: false;
  hideOnZoom: false;
};
type PreviewHost = {
  addDOMWidget: (
    name: string,
    type: string,
    element: HTMLElement,
    options: PreviewOptions,
  ) => NodeWidget;
};

const previews = new Map<string, CanvasPreview>();

/**
 * Keep one on-canvas JPEG for a live session without starting another exchange.
 */
class CanvasPreview {
  /**
   * Remember the node widget so the session can remove it later.
   * @param image - The element that displays JPEG frames.
   * @param root - The widget element removed with the session.
   * @param widget - The ComfyUI DOM widget mounted on the node.
   * @param node - The graph node that owns the widget.
   * @param previousSize - The node size before the preview grew it.
   */
  constructor(
    readonly image: HTMLImageElement,
    private readonly root: HTMLElement,
    private readonly widget: NodeWidget,
    readonly node: FoundNode,
    private readonly previousSize: [number, number],
  ) {}

  /** Drop the frame, unregister the widget, and restore the node size. */
  close(): void {
    this.image.removeAttribute('src');
    releaseText(this.root);
    this.node.ensureWidgetRemoved(this.widget);
    this.root.remove();
    this.node.setSize(this.previousSize);
    this.node.setDirtyCanvas(true, true);
  }
}

/**
 * Report whether this ComfyUI build can mount a DOM widget on the node.
 * @param node - The graph node selected for the session.
 * @returns Whether addDOMWidget is available on that node.
 */
function hasPreviewHost(node: FoundNode): node is FoundNode & PreviewHost {
  if (!('addDOMWidget' in node)) return false;
  return typeof node.addDOMWidget === 'function';
}

/**
 * Show one JPEG frame without restarting decode when the URL is unchanged.
 * @param image - The preview image in the panel or on the node.
 * @param frame - A data URL for one JPEG.
 */
function applyFrame(image: HTMLImageElement, frame: string): void {
  image.decoding = 'async';
  if (image.src === frame) {
    image.hidden = false;
    return;
  }
  image.src = frame;
  image.hidden = false;
}

/**
 * Build the node element that shows the waiting state and later frames.
 * @returns The widget root and its image.
 */
function buildPreviewElement(): { root: HTMLDivElement; image: HTMLImageElement } {
  const root = element('div');
  root.className = 'reactor-preview reactor-canvas-preview';
  root.style.setProperty('--comfy-widget-min-height', `${previewMinHeight}px`);
  root.style.minHeight = `${previewMinHeight}px`;
  const image = element('img');
  image.hidden = true;
  image.decoding = 'async';
  setTextAttribute(image, 'alt', message('live.output'));
  root.append(image, element('p', message('live.waitingVideo')));
  return { root, image };
}

/**
 * Remove a previous preview widget so a node keeps a single live view.
 * @param node - The graph node that may already show a preview.
 */
function removeNamedWidget(node: FoundNode): void {
  const stale = node.widgets?.find((widget) => widget.name === widgetName);
  if (!stale) return;
  node.ensureWidgetRemoved(stale);
}

/**
 * Release any preview already mounted on this node, including a stale widget.
 * @param node - The graph node about to receive the current session.
 */
function releaseNode(node: FoundNode): void {
  const leases: string[] = [];
  for (const [lease, preview] of previews) {
    if (preview.node === node) leases.push(lease);
  }
  for (const lease of leases) closeCanvasPreview(lease);
  removeNamedWidget(node);
}

/**
 * Mount the preview widget and grow the node enough to show it.
 * @param node - The graph node that can host a DOM widget.
 * @returns The mounted preview, or undefined when mounting fails.
 */
function mountPreview(node: FoundNode & PreviewHost): CanvasPreview | undefined {
  releaseNode(node);
  const view = buildPreviewElement();
  const [width, height] = node.size;
  const options: PreviewOptions = { serialize: false, hideOnZoom: false };
  try {
    const widget = node.addDOMWidget(widgetName, 'reactorPreview', view.root, options);
    widget.serialize = false;
    widget.options.serialize = false;
    const fitted = node.computeSize();
    node.setSize([Math.max(width, fitted[0]), Math.max(height, fitted[1])]);
    node.setDirtyCanvas(true, true);
    return new CanvasPreview(view.image, view.root, widget, node, [width, height]);
  } catch {
    releaseText(view.root);
    view.root.remove();
    return undefined;
  }
}

/**
 * Show the live JPEG on the invited node. A second call for the same session does nothing.
 * @param lease - The session id that owns this preview.
 * @param nodeId - The graph node id from the session invitation.
 */
export function openCanvasPreview(lease: string, nodeId: string): void {
  if (previews.has(lease) || nodeId.length === 0) return;
  const node = findCanvasNode(nodeId);
  if (!node || !hasPreviewHost(node)) return;
  const preview = mountPreview(node);
  if (!preview) return;
  previews.set(lease, preview);
}

/**
 * Paint one exchange frame on the panel and, when mounted, on the node.
 * @param lease - The session id that owns the canvas preview.
 * @param image - The panel image that already displayed this feed.
 * @param preview - The validated base64 JPEG, empty when unchanged.
 */
export function paintSessionPreview(lease: string, image: HTMLImageElement, preview: string): void {
  if (preview.length === 0) return;
  const frame = `data:image/jpeg;base64,${preview}`;
  applyFrame(image, frame);
  const previewOwner = previews.get(lease);
  if (!previewOwner) return;
  applyFrame(previewOwner.image, frame);
}

/**
 * Remove the node preview for a session. Other sessions are left alone.
 * @param lease - The session id whose preview should close.
 */
export function closeCanvasPreview(lease: string): void {
  const preview = previews.get(lease);
  if (!preview) return;
  previews.delete(lease);
  preview.close();
}
