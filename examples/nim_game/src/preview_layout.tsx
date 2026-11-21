import React from 'react';
import {flushSync} from 'react-dom';
import {createRoot} from 'react-dom/client';
import {Frame} from './Nim';
import {loadSceneFonts} from './Fonts';

const container = document.getElementById('root')!;
const root = createRoot(container);
const textSelector = '[data-qc-text], svg text';

function hasPaint(node: Element) {
  let opacity = 1;
  for (let ancestor: Element | null = node; ancestor && ancestor !== container; ancestor = ancestor.parentElement) {
    const style = getComputedStyle(ancestor);
    if (style.visibility === 'hidden' || style.display === 'none') return 0;
    opacity *= Number(style.opacity);
  }
  return opacity;
}

function trailMargin(element: Element, trail: Element) {
  for (let ancestor: Element | null = element; ancestor; ancestor = ancestor.parentElement) {
    const filter = getComputedStyle(ancestor).filter;
    const id = filter.match(/#([^"'\s)]+)/)?.[1];
    const blur = id && document.getElementById(id)?.querySelector('feGaussianBlur');
    if (blur) {
      const x = blur.stdDeviationX.baseVal;
      const y = blur.stdDeviationY.baseVal;
      return [3 * x, 3 * y];
    }
    if (ancestor === trail) break;
  }
  return [0, 0];
}

function inspectFrame(frame: number, fps: number) {
  flushSync(() => root.render(<Frame frame={frame} fps={fps} />));

  return Array.from(container.querySelectorAll(textSelector)).flatMap((element) => {
    const text = element.textContent?.trim();
    if (!text || element.parentElement?.closest(textSelector)) {
      return [];
    }

    const trail = element.closest('[data-qc-trail]');
    const flight = element.closest('[data-qc-flight], [data-qc-exit]');
    const opacity = hasPaint(element);
    if (opacity < (trail ? 0.002 : 0.02)) {
      return [];
    }

    const {left, top, right, bottom, width, height} = element.getBoundingClientRect();
    if (!width || !height) {
      return [];
    }
    const digitRoll = element.closest('[data-qc-digit-roll]');
    const slot = digitRoll ? Array.from(container.querySelectorAll('[data-qc-digit-roll]')).indexOf(digitRoll) : null;
    const viewport = digitRoll instanceof SVGSVGElement ? digitRoll.getBoundingClientRect() : null;
    const bounds = viewport ? [
      Math.max(left, viewport.left), Math.max(top, viewport.top),
      Math.min(right, viewport.right), Math.min(bottom, viewport.bottom),
    ] : [left, top, right, bottom];
    if (bounds[0] >= bounds[2] || bounds[1] >= bounds[3]) return [];
    const [padX, padY] = trail ? trailMargin(element, trail) : [0, 0];
    const role = element.getAttribute('data-qc-text') === 'archives'
      ? 'archives' : element.closest('[data-qc-role]')?.getAttribute('data-qc-role') ?? 'stage';
    const paintBounds = [bounds[0] - padX, bounds[1] - padY, bounds[2] + padX, bounds[3] + padY];
    return [{text, bounds, paintBounds, opacity, role, trail: Boolean(trail), flight: Boolean(flight), slot}];
  });
}

function inspectSpecial(frame: number, fps: number) {
  const labels = inspectFrame(frame, fps);
  const callout = container.querySelector('[data-b03-callout="label"]');
  const calloutText = callout?.querySelector('text');
  const leftJaw = container.querySelector('[data-b03-jaw-left]');
  const guideElement = container.querySelector('[data-b03-callout="guide"]');
  const guide = guideElement instanceof SVGGeometryElement ? guideElement
    : guideElement?.querySelector('path, line');
  const calloutLayout = calloutText && leftJaw && guide instanceof SVGGeometryElement && hasPaint(calloutText) >= .1
    ? {
      text: calloutText.textContent?.trim(),
      labelRight: calloutText.getBoundingClientRect().right,
      jawLeft: Number(leftJaw.getAttribute('data-b03-jaw-left')),
      guideLength: guide.getTotalLength(),
    }
    : null;
  const slots = Array.from(container.querySelectorAll('[data-qc-digit-roll]'), (node) => ({
    height: node instanceof SVGSVGElement ? node.height.baseVal.value : 0,
    em: Number(node.getAttribute('data-qc-slot-size')),
    cssOverflow: getComputedStyle(node).overflow,
    isSvgViewport: node instanceof SVGSVGElement,
  }));
  const threads = Array.from(container.querySelectorAll('[data-qc-speed-thread]'), (node) => {
    const {left, top, right, bottom} = node.getBoundingClientRect();
    const role = node.closest('[data-qc-role]')?.getAttribute('data-qc-role') ?? 'headline';
    return {bounds: [left, top, right, bottom], role, opacity: hasPaint(node)};
  }).filter(thread => thread.opacity >= .002);
  return {frame, labels, callout: calloutLayout, slots, threads};
}

Object.assign(window, {
  loadNimSceneFonts: loadSceneFonts,
  inspectNimFrames: (first: number, stop: number, fps: number) =>
    Array.from({length: stop - first}, (_, index) => inspectFrame(first + index, fps)),
  inspectNimSelectedFrames: (frames: number[], fps: number) =>
    frames.map(frame => inspectFrame(frame, fps)),
  inspectNimSpecialFrames: (first: number, stop: number, fps: number) =>
    Array.from({length: stop - first}, (_, index) => inspectSpecial(first + index, fps)),
  inspectNimRecap: (frame: number) => ({
    texts: inspectFrame(frame, 60),
    boardStates: Array.from(container.querySelectorAll('[data-recap-node]'), (node) =>
      node.getAttribute('data-recap-node'),
    ),
  }),
  inspectNimFontCandidates: (frame: number) => {
    inspectFrame(frame, 60);
    return Array.from(container.querySelectorAll(textSelector + ', svg tspan')).flatMap((node, index) => {
      const text = node.textContent?.trim();
      if (!text || node.closest('[data-qc-trail]') || hasPaint(node) < .1) return [];
      if (node.children.length && !Array.from(node.childNodes).some(
        child => child.nodeType === Node.TEXT_NODE && child.textContent?.trim(),
      )) return [];
      const role = node.getAttribute('data-qc-text') === 'archives'
        ? 'archives' : node.closest('[data-qc-role]')?.getAttribute('data-qc-role') ?? 'stage';
      const attributes = getComputedStyle(node);
      const childFamilies = Array.from(node.querySelectorAll('tspan'), child => getComputedStyle(child).fontFamily);
      node.setAttribute('data-qa-font-id', String(index));
      return [{id: index, text, role, family: attributes.fontFamily, weight: attributes.fontWeight,
        childFamilies, size: attributes.fontSize, spacing: attributes.letterSpacing, lineHeight: attributes.lineHeight}];
    });
  },
  inspectNimRoutes: (first: number, stop: number, fps: number) =>
    Array.from({length: stop - first}, (_, index) => {
      const frame = first + index;
      inspectFrame(frame, fps);
      return Array.from(container.querySelectorAll('[data-route-actor]'), (node) => {
        const actor = node.getAttribute('data-route-actor');
        const rail = container.querySelector(`[data-rail-player="${actor}"]`);
        return {
          frame, actor,
          x: Number(node.getAttribute('data-route-x')),
          y: Number(node.getAttribute('data-route-y')),
          targetY: rail ? Number(rail.getAttribute('data-rail-y')) : null,
        };
      });
    }).flat(),
});
