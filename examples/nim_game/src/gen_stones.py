"""Render four deterministic orthographic obsidian sprites and their SVG overlay geometry."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


WIDTH, HEIGHT = 480, 360
SUPERSAMPLE = 2
YAW = (-6.0, -2.0, 3.0, 6.0)
SEED = 260311
TOP_RADIUS = 1.0
TOP_Z = 0.57
CHAMFER = 0.135
SIDE_Z = TOP_Z - CHAMFER
OUTER_RADIUS = TOP_RADIUS + CHAMFER / math.cos(math.pi / 8)
BASE_RADIUS = OUTER_RADIUS * 0.923
ELEVATION = math.radians(28)
PIXELS_PER_UNIT = 201.0
PROJECTION_CENTER = np.array([240.0, 229.0])
ANCHOR = (240, 180)
VIEW = np.array([0.0, math.cos(ELEVATION), math.sin(ELEVATION)])
UP_IN_IMAGE = np.array([0.0, math.sin(ELEVATION), -math.cos(ELEVATION)])
OUTPUT = Path(__file__).resolve().parent / "assets"


def srgb(hex_value: str) -> np.ndarray:
    value = np.array([int(hex_value[i:i + 2], 16) for i in (0, 2, 4)]) / 255.0
    return np.where(value <= 0.04045, value / 12.92, ((value + 0.055) / 1.055) ** 2.4)


def linear_to_bytes(rgb: np.ndarray) -> np.ndarray:
    rgb = np.clip(rgb, 0, 1)
    encoded = np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * rgb ** (1 / 2.4) - 0.055)
    return np.round(encoded * 255).astype(np.uint8)


def unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def light_vector(azimuth: float, elevation: float) -> np.ndarray:
    az, el = np.radians([azimuth, elevation])
    return np.array([np.cos(az) * np.cos(el), np.sin(az) * np.cos(el), np.sin(el)])


KEY = light_vector(-135, 42)
RIM = light_vector(-15, 18)
SOFTBOX = light_vector(36, 67)
GOLD = srgb("C9A96A")
PLATINUM = srgb("FFF5D8")
RIM_GOLD = srgb("D9B978")
OBSIDIAN_DARK = srgb("0D1016")
OBSIDIAN_LIGHT = srgb("191F28")


@dataclass
class Face:
    points: np.ndarray
    normal: np.ndarray
    material: str


def project(points: np.ndarray) -> np.ndarray:
    return np.column_stack((points[:, 0], points @ UP_IN_IMAGE)) * PIXELS_PER_UNIT + PROJECTION_CENTER


def octagon(radius: float, z: float, yaw: float) -> np.ndarray:
    angle = np.arange(8) * math.pi / 4 + math.pi / 8 + math.radians(yaw)
    return np.column_stack((radius * np.cos(angle), radius * np.sin(angle), np.full(8, z)))


def mesh(yaw: float) -> tuple[list[Face], np.ndarray, np.ndarray, np.ndarray]:
    top = octagon(TOP_RADIUS, TOP_Z, yaw)
    rim = octagon(OUTER_RADIUS, SIDE_Z, yaw)
    bottom = octagon(BASE_RADIUS, 0.0, yaw)
    faces = [Face(top, np.array([0.0, 0.0, 1.0]), "top")]
    for i in range(8):
        j = (i + 1) % 8
        for upper, lower, material in ((top, rim, "gold"), (rim, bottom, "side")):
            points = np.array([upper[i], lower[i], lower[j], upper[j]])
            normal = unit(np.cross(points[1] - points[0], points[3] - points[0]))
            faces.append(Face(points, normal, material))
    return faces, top, rim, bottom


def ggx(normal: np.ndarray, direction: np.ndarray, roughness: np.ndarray, f0: np.ndarray) -> np.ndarray:
    half = unit(direction + VIEW)
    nv = np.clip(normal @ VIEW, 0.0001, 1.0)
    nl = np.clip(normal @ direction, 0, 1.0)
    nh = np.clip(normal @ half, 0, 1.0)
    vh = np.clip(VIEW @ half, 0, 1.0)
    alpha2 = roughness ** 4
    distribution = alpha2 / (np.pi * (nh * nh * (alpha2 - 1) + 1) ** 2)
    visibility_v = 2 * nv / (nv + np.sqrt(alpha2 + (1 - alpha2) * nv * nv))
    visibility_l = 2 * nl / (nl + np.sqrt(alpha2 + (1 - alpha2) * nl * nl))
    fresnel = f0 + (1 - f0) * (1 - vh) ** 5
    return (distribution * visibility_v * visibility_l / (4 * nv))[:, None] * fresnel


def shade(face: Face, world: np.ndarray, grain: np.ndarray) -> np.ndarray:
    normal = np.broadcast_to(face.normal, world.shape).copy()
    if face.material == "top":
        normal[:, :2] += grain[:, :2] * 0.03
        # Resolve the sub-millimetre radius where the top meets the gold chamfer.
        edges = np.roll(face.points[:, :2], -1, axis=0) - face.points[:, :2]
        walls = unit(np.column_stack((edges[:, 1], -edges[:, 0])))
        halfspace = np.sum(walls * face.points[:, :2], axis=1)
        distances = halfspace - world[:, :2] @ walls.T
        nearest = np.argmin(distances, axis=1)
        wall = walls[nearest]
        edge_distance = distances[np.arange(len(world)), nearest]
        edge = np.exp(-((edge_distance - .010) / .009) ** 2)
        normal[:, :2] += wall * (.125 * edge)[:, None]
        normal = unit(normal)
        # A wide studio card is visible as a subtle pass through the satin surface.
        soft_card = np.exp(-((world[:, 0] + .47 * world[:, 1] + .18) / .73) ** 2)
        falloff = np.clip(.26 + .45 * soft_card - .23 * world[:, 1] + .10 * grain[:, 2], 0, 1)
        body = OBSIDIAN_DARK + (OBSIDIAN_LIGHT - OBSIDIAN_DARK) * falloff[:, None]
        roughness = 0.57 + grain[:, 2] * 0.035
        sheen = ggx(normal, SOFTBOX, roughness, np.full(3, .035))
        key_edge = np.maximum(wall @ unit(KEY[:2]), 0) ** 6
        rim_edge = np.maximum(wall @ unit(RIM[:2]), 0) ** 5
        edge_reflection = edge[:, None] * (
            PLATINUM * (.73 * key_edge)[:, None] + RIM_GOLD * (.058 * rim_edge)[:, None]
        )
        return (body * (.88 + .21 * np.maximum(normal @ KEY, 0))[:, None]
                + sheen * np.array([.08, .105, .14]) + edge_reflection)
    if face.material == "gold":
        chamfer_fraction = np.clip((TOP_Z - world[:, 2]) / CHAMFER, 0, 1)
        brush = .67 * np.sin(chamfer_fraction * 112 + .6 * grain[:, 2]) + .33 * grain[:, 2]
        normal[:, 2] += 0.012 * brush
        normal = unit(normal)
        roughness = .31 + .024 * brush
        exposure = np.maximum(normal @ KEY, 0)
        right = np.clip(normal[:, 0], 0, 1)
        # Warm studio bounce is strongest on the lit 45-degree metal, not the body.
        ambient = GOLD * (.098 + .43 * exposure ** 2.7 + .036 * right)[:, None]
        key_specular = ggx(normal, KEY, roughness, GOLD) * PLATINUM * 1.24
        rim_specular = ggx(normal, RIM, roughness + .11, GOLD) * RIM_GOLD * .43
        # A thin reflected strip from the large top softbox falls along the inner lip.
        lip = np.exp(-((chamfer_fraction - .10) / .082) ** 2)
        lip_reflection = PLATINUM * (1.02 * lip * exposure ** 4.25)[:, None]
        return (ambient + key_specular + rim_specular + lip_reflection) * (1 + .038 * brush[:, None])

    left = np.clip(-normal[:, 0], 0, 1)
    right = np.clip(normal[:, 0], 0, 1)
    height = np.clip(world[:, 2] / SIDE_Z, 0, 1)
    side_mix = np.clip(.18 + .56 * left + .15 * height + .045 * grain[:, 2], 0, 1)
    body = OBSIDIAN_DARK + (OBSIDIAN_LIGHT - OBSIDIAN_DARK) * side_mix[:, None]
    roughness = np.full(len(world), .50)
    rim_specular = ggx(normal, RIM, roughness, np.full(3, .04))
    # The lower wall tightens nearly to black and retains a narrow warm rim to the right.
    edge = np.exp(-((1 - height) / .105) ** 2) * right**1.9
    return (body * (.60 + .35 * height)[:, None]
            + rim_specular * RIM_GOLD * .24
            + RIM_GOLD * (.032 * edge)[:, None])


def draw_triangle(
    pixels: np.ndarray,
    z_buffer: np.ndarray,
    grain: np.ndarray,
    points: np.ndarray,
    face: Face,
) -> None:
    xy = project(points) * SUPERSAMPLE
    x0, y0 = np.maximum(np.floor(xy.min(axis=0)).astype(int), 0)
    x1, y1 = np.minimum(np.ceil(xy.max(axis=0)).astype(int) + 1, pixels.shape[1::-1])
    if x0 >= x1 or y0 >= y1:
        return
    xs, ys = np.meshgrid(np.arange(x0, x1) + .5, np.arange(y0, y1) + .5)
    weights = np.linalg.inv(np.column_stack((xy, np.ones(3))).T) @ np.vstack((
        xs.ravel(), ys.ravel(), np.ones(xs.size),
    ))
    depth = points @ VIEW
    distance = depth @ weights
    closer = distance > z_buffer[y0:y1, x0:x1].ravel()
    inside = (weights.min(axis=0) >= -1e-9) & closer
    iy, ix = np.nonzero(inside.reshape(xs.shape))
    world = weights[:, inside].T @ points
    encoded = linear_to_bytes(shade(face, world, grain[iy + y0, ix + x0]))
    pixels[iy + y0, ix + x0, :3] = encoded
    pixels[iy + y0, ix + x0, 3] = 255
    z_buffer[iy + y0, ix + x0] = distance[inside]


def points_json(points: np.ndarray) -> list[list[float]]:
    return np.around(points, 3).tolist()


def outline(points: np.ndarray) -> np.ndarray:
    """Visible convex outline: the rear chamfer edge sits behind the top face."""
    points_sorted = sorted(map(tuple, points))

    def chain(ordered):
        result = []
        for point in ordered:
            while len(result) >= 2:
                a, b = result[-2:]
                turn = (b[0] - a[0]) * (point[1] - b[1]) - (b[1] - a[1]) * (point[0] - b[0])
                if turn > 0:
                    break
                result.pop()
            result.append(point)
        return result

    return np.array(chain(points_sorted)[:-1] + chain(reversed(points_sorted))[:-1])


def render_variant(index: int, yaw: float) -> dict:
    faces, top, rim, bottom = mesh(yaw)
    dims = (HEIGHT * SUPERSAMPLE, WIDTH * SUPERSAMPLE)
    pixels = np.zeros((*dims, 4), dtype=np.uint8)
    z_buffer = np.full(dims, -np.inf)
    rng = np.random.default_rng(SEED + index * 743)
    grain = rng.uniform(-1, 1, (*dims, 3)).astype(np.float32)

    for face in faces:
        if face.normal @ VIEW <= 0:
            continue
        for end in range(2, len(face.points)):
            draw_triangle(pixels, z_buffer, grain, face.points[[0, end - 1, end]], face)

    image = Image.fromarray(pixels).resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    image.save(OUTPUT / f"stone_v{index}.png", compress_level=9)
    projected_rim = project(rim)
    projected_top = project(top)
    projected_bottom = project(bottom)
    top_lip = []
    lit_paths = []
    for i in range(8):
        j = (i + 1) % 8
        normal = faces[1 + 2 * i].normal
        if unit(normal[:2]) @ unit(KEY[:2]) > .57:
            lit_paths.append(points_json(projected_top[[i, j]]))
        if normal @ VIEW > 0 and normal @ KEY > .55:
            top_lip.append([i, j])
    opaque = np.asarray(image)[..., 3] > 127
    iy, ix = np.nonzero(opaque)
    return {
        "yaw": yaw,
        "alphaBounds": [int(ix.min()), int(iy.min()), int(ix.max() + 1), int(iy.max() + 1)],
        "topRing": points_json(projected_top),
        "chamferRing": points_json(projected_rim),
        "baseRing": points_json(projected_bottom),
        "lipOutline": points_json(outline(np.vstack((projected_top, projected_rim)))),
        "litEdges": top_lip,
        "litPaths": lit_paths,
        "contact": [float(PROJECTION_CENTER[0]), round(float(projected_bottom[:, 1].max()), 3)],
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    variants = [render_variant(i, yaw) for i, yaw in enumerate(YAW)]
    geometry = {"width": WIDTH, "height": HEIGHT, "anchor": ANCHOR, "variants": variants}
    (OUTPUT / "stone_geometry.json").write_text(json.dumps(geometry, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
