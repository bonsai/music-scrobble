# MMD Instruction: Houdini Fire Simulation & WebGL (WASM) Rendering

## 1. Create the fire in Houdini
- **Start a new Houdini scene** (`File → New`).
- **Add a Geometry node** (`Tab → Geometry`) and rename to `fire`.
- **Insert a Pyro Solver** (`Tab → DOP Network → Pyro Solver`).
  - Connect a source (Box/Sphere) → `Pyro Solver → out` → `Merge → out` of the Geometry node.
- **Add a Pyro Source** inside the DOPs network (`Tab → Pyro → Pyro Source`).
  - Connect its `out` to the `in` of the Pyro Solver.
- **Set up smoke/fire volumes** in the Pyro Solver parameters:
  - Enable **Smoke**, set high **Temperature**, low **Density** for flame.
  - Enable **Fire**, adjust **Fuel**, **Smoke**, **Temperature** as desired.
- *(Optional) Add a Temperature source for more realistic flame behavior.*
- **Set the time range** (e.g., frames 1‑120) in the Pyro Solver.
- **Bake the simulation** (`Ctrl‑B` or the Bake button on the Pyro Solver).
- **Export the geometry** (`File → Export → Geometry → .bgeo`) and save as `fire.bgeo` in a folder served by your web server (e.g., `public/`).

## 2. Load & render the fire in the browser (Houdini Engine JS + WebGL/WASM)
### 2.1 Install packages
```bash
npm init -y
npm install houdini-engine three
```
> *Houdini Engine JS requires a licensed Houdini installation on the build machine; the WASM binary is generated from that installation.*

### 2.2 Minimal HTML + JavaScript (`index.html`)
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Houdini Fire – WebGL (WASM)</title>
  <style>
    body {margin:0; overflow:hidden;}
    canvas {display:block;}
  </style>
</head>
<body>
  <script type="module">
    import { Engine } from 'houdini-engine';
    import * as THREE from 'three';

    // ----- Three.js scene -----
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, innerWidth / innerHeight, 0.1, 1000);
    camera.position.set(0, 0, 5);
    const renderer = new THREE.WebGLRenderer({antialias:true});
    renderer.setSize(innerWidth, innerHeight);
    document.body.appendChild(renderer.domElement);
    scene.add(new THREE.AmbientLight(0xffffff, 0.5));
    const dirLight = new THREE.DirectionalLight(0xffffff, 1);
    dirLight.position.set(5,5,5);
    scene.add(dirLight);

    // ----- Houdini Engine -----
    const engine   = await Engine.create();           // loads WASM
    const session  = await engine.createSession();    // creates a Houdini session

    // Load the baked .bgeo file
    const filePath = '/fire.bgeo';                    // adjust path if needed
    await session.loadFile(filePath);                // loads geometry into /out1

    // Cook the node so the simulation is evaluated
    const node = await session.getNode('/out1');
    await session.cookNode(node);

    // ----- Convert Houdini geometry to THREE objects -----
    const hapiGeom = await node.getGeometry();        // HAPI_GeoInfo wrapper
    const positions = hapiGeom.getFloatArray('P');   // vertex positions (float32)
    const primAcrossEdges = hapiGeom.getUint32Array('primacrossedges'); // face indices

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setIndex(primAcrossEdges);

    // Simple fire‑looking shader material
    const material = new THREE.ShaderMaterial({
      uniforms: {
        uTime:   { value: 0 },
        uColor:  { value: new THREE.Color(0xff4500) } // orange‑red
      },
      vertexShader: `
        attribute vec3 position;
        uniform float uTime;
        void main() {
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0);
        }
      `,
      fragmentShader: `
        precision mediump float;
        uniform float uTime;
        uniform vec3 uColor;
        void main() {
          float intensity = smoothstep(0.0,1.5, length(position)*0.2 + uTime);
          vec3 col = uColor * intensity;
          gl_FragColor = vec4(col, intensity);
        }
      `,
      transparent: true,
      depthWrite: false
    });

    const mesh = new THREE.Mesh(geometry, material);
    scene.add(mesh);

    // ----- Animation loop -----
    const clock = new THREE.Clock();
    function animate() {
      const delta = clock.getDelta();
      material.uniforms.uTime.value += delta;   // drive the shader
      renderer.render(scene, camera);
      requestAnimationFrame(animate);
    }
    animate();

    // ----- Resize handling -----
    window.addEventListener('resize', () => {
      camera.aspect = innerWidth / innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(innerWidth, innerHeight);
    });
  </script>
</body>
</html>
```

### 2.3 How it works (summary)
| Step | What happens |
|------|--------------|
| **Engine.create()** | Loads the Houdini Engine WebAssembly (`houdini_engine.wasm`). |
| **session.loadFile()** | Streams the `.bgeo` into the WASM Houdini environment. |
| **session.getNode('/out1')** | After loading, Houdini creates an `/out1` node containing the geometry. |
| **session.cookNode()** | Executes the Pyro Solver, baking the smoke/fire volumes. |
| **node.getGeometry()** | Returns raw attribute arrays (positions, etc.) that we feed into Three.js. |
| **THREE.BufferGeometry + ShaderMaterial** | Renders the geometry; the `uTime` uniform animates the fire. |
| **Animation loop** | Increments `uTime` each frame, giving the illusion of moving flames. |

## 3️⃣ Quick checklist before running
- **Houdini license** – needed on the machine that builds the WASM binary.
- **Serve the `.bgeo` file** – adjust `filePath` in the script to point at where you host `fire.bgeo`.
- **Node version** – the example uses ES‑modules (`type="module"`). Make sure your web server serves `.js` with the correct MIME type.
- **Browser support** – modern browsers (Chrome, Edge, Firefox, Safari) support WebGL2 and the WASM module used by Houdini Engine JS.

## 4️⃣ Optional enhancements
- **Use temperature/density volumes** – request those attributes via `getFloatArray('temperature')` etc., and feed them into a more sophisticated fragment shader.
- **Full volumetric rendering** – employ `THREE.Volume` + custom `ShaderMaterial` that samples a 3D density texture.
- **Runtime parameter control** – export Pyro Solver parameters as attributes and update them via `node.setFloatArray('fuel', newValues)` before cooking.
- **Multiple fire instances** – duplicate `/out1` in Houdini with different transforms, or pack many streams into a single `.bgeo` and extract by primitive groups.
- **Physics‑based interaction** – modify the position attribute each frame using a physics engine (e.g., `cannon-es`) to make the fire react to forces.

## 5️⃣ TL;DR
> **Create a pyro simulation in Houdini → bake to `.bgeo` → load with Houdini Engine JS (WASM) in the browser → feed the geometry into a Three.js `BufferGeometry` and render with an animated shader.**

--- 

*If you meant a different “mmd” instruction (e.g., MikuMikuDance model steps), please let me know and I’ll adjust the file accordingly.*