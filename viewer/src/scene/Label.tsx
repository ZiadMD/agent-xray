import { Billboard, Text } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import * as THREE from 'three'
import monoFont from '@fontsource/jetbrains-mono/files/jetbrains-mono-latin-500-normal.woff?url'
import { useTuningValue } from '../tuning/context'
import { useLiveGraph } from './liveGraph'

interface TroikaText extends THREE.Mesh {
  fillOpacity: number
}

const world = new THREE.Vector3()

interface LabelProps {
  text: string
  y: number
  size?: number
  /** Base opacity before distance fading (the HUD text color sits at ~70%). */
  opacity?: number
  letterSpacing?: number
}

/** Small billboarded mono label that fades as it gets far from the camera. */
export function Label({ text, y, size = 1, opacity = 0.72, letterSpacing = 0.04 }: LabelProps) {
  const ref = useRef<TroikaText>(null)
  const tuning = useTuningValue()
  const { layout } = useLiveGraph()

  useFrame(({ camera }) => {
    const label = ref.current
    if (!label) return
    label.getWorldPosition(world)
    const distance = camera.position.distanceTo(world)
    const near = layout.radius * 1.4
    const far = layout.radius * 4.5
    const fade = 1 - THREE.MathUtils.smoothstep(distance, near, far)
    label.fillOpacity = opacity * (0.25 + 0.75 * fade)
  })

  return (
    <Billboard position={[0, y, 0]}>
      <Text
        ref={ref}
        font={monoFont}
        fontSize={tuning.labelSize * size}
        letterSpacing={letterSpacing}
        color={tuning.hud}
        anchorX="center"
        anchorY="top"
        material-toneMapped={false}
        material-depthWrite={false}
      >
        {text}
      </Text>
    </Billboard>
  )
}
