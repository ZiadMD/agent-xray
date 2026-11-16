import * as THREE from 'three'

/** Glowing orb: a dim core with a fresnel rim, slow breathing and a faint inner shimmer. */
export function createOrbMaterial(phase: number): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    uniforms: {
      uCore: { value: new THREE.Color() },
      uRim: { value: new THREE.Color() },
      uGlow: { value: 1 },
      uTime: { value: 0 },
      uPhase: { value: phase },
    },
    vertexShader: /* glsl */ `
      varying vec3 vNormal;
      varying vec3 vView;
      varying vec3 vLocal;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        vNormal = normalize(normalMatrix * normal);
        vView = normalize(-mv.xyz);
        vLocal = position;
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 uCore;
      uniform vec3 uRim;
      uniform float uGlow;
      uniform float uTime;
      uniform float uPhase;
      varying vec3 vNormal;
      varying vec3 vView;
      varying vec3 vLocal;
      void main() {
        float facing = max(dot(normalize(vNormal), normalize(vView)), 0.0);
        float fresnel = pow(1.0 - facing, 2.4);
        float breathe = 0.84 + 0.16 * sin(uTime * 1.25 + uPhase);
        vec3 p = vLocal * 5.0;
        float shimmer = sin(p.x + uTime * 0.9) * sin(p.y - uTime * 0.7) * sin(p.z + uTime * 0.5);
        vec3 core = uCore * (0.45 + 0.55 * facing) * breathe;
        vec3 color = core + uRim * (fresnel * (1.1 + 0.5 * breathe) + shimmer * 0.05) * uGlow;
        gl_FragColor = vec4(color, 1.0);
        #include <colorspace_fragment>
      }
    `,
  })
}

/** Faint translucent shell around the children of a subgraph. */
export function createShellMaterial(): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    uniforms: {
      uColor: { value: new THREE.Color() },
      uOpacity: { value: 0.3 },
    },
    vertexShader: /* glsl */ `
      varying vec3 vNormal;
      varying vec3 vView;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        vNormal = normalize(normalMatrix * normal);
        vView = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor;
      uniform float uOpacity;
      varying vec3 vNormal;
      varying vec3 vView;
      void main() {
        float facing = abs(dot(normalize(vNormal), normalize(vView)));
        float rim = pow(1.0 - facing, 3.0);
        gl_FragColor = vec4(uColor, (0.04 + rim) * uOpacity);
        #include <colorspace_fragment>
      }
    `,
  })
}

let glowTexture: THREE.Texture | null = null

/** Soft radial gradient used by halos and nebula sprites (built once). */
export function getGlowTexture(): THREE.Texture {
  if (glowTexture) return glowTexture
  const size = 128
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const ctx = canvas.getContext('2d') as CanvasRenderingContext2D
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
  gradient.addColorStop(0, 'rgba(255,255,255,1)')
  gradient.addColorStop(0.25, 'rgba(255,255,255,0.45)')
  gradient.addColorStop(0.6, 'rgba(255,255,255,0.08)')
  gradient.addColorStop(1, 'rgba(255,255,255,0)')
  ctx.fillStyle = gradient
  ctx.fillRect(0, 0, size, size)
  glowTexture = new THREE.CanvasTexture(canvas)
  glowTexture.colorSpace = THREE.SRGBColorSpace
  return glowTexture
}

/** Twinkling star dust (points with size attenuation). */
export function createStarMaterial(): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: { value: 0 },
      uOpacity: { value: 0.8 },
      uPixelRatio: { value: 1 },
    },
    vertexShader: /* glsl */ `
      attribute float aSize;
      attribute float aPhase;
      attribute vec3 aColor;
      uniform float uTime;
      uniform float uPixelRatio;
      varying float vTwinkle;
      varying vec3 vColor;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * mv;
        vTwinkle = 0.55 + 0.45 * sin(uTime * (0.4 + fract(aPhase) * 0.9) + aPhase * 6.2831);
        vColor = aColor;
        gl_PointSize = aSize * uPixelRatio * (110.0 / -mv.z);
      }
    `,
    fragmentShader: /* glsl */ `
      uniform float uOpacity;
      varying float vTwinkle;
      varying vec3 vColor;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        float a = smoothstep(0.5, 0.0, d);
        gl_FragColor = vec4(vColor, a * a * vTwinkle * uOpacity);
        #include <colorspace_fragment>
      }
    `,
  })
}
