/* ============================================================
   无人机飞行模拟 3D 前端
   ============================================================ */
"use strict";

/* ---------- 前端日志（上报到后端 logs/frontend.log）---------- */
function logFrontend(entry, level = "INFO") {
  console.log(`[DroneSim FE] ${entry}`);
  try {
    fetch("/api/frontend-log", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entry, level }),
    }).catch(() => {});
  } catch (e) { /* 静默失败 */ }
}

/* ---------- 全局状态 ---------- */
const state = {
  simData: null,
  playTime: 0,
  playing: false,
  paused: false,
  speed: 1,
  finished: false,
  rainActive: false,
  lastFrameDt: 0,   // 上一帧实际帧间隔（用于轨迹点采样）
};

/* ---------- DOM ---------- */
const $ = id => document.getElementById(id);
const menuScreen   = $("menu-screen");
const flightScreen = $("flight-screen");
const canvas       = $("three-canvas");
const btnStart     = $("btn-start");
const inputMinutes = $("input-minutes");
const inputSeed    = $("input-seed");
const menuStatus   = $("menu-status");

const hudTime      = $("hud-time");
const hudLatlon    = $("hud-latlon");
const hudAlt       = $("hud-alt");
const hudBattery   = $("hud-battery");
const hudMode      = $("hud-mode");
const hudEvent     = $("hud-event");
const timelineFill = $("timeline-fill");
const timelineLabel = $("timeline-label");
const btnPause     = $("btn-pause");
const btnSpeed1    = $("btn-speed1");
const btnSpeed4    = $("btn-speed4");
const btnSpeed8    = $("btn-speed8");
const btnBack      = $("btn-back");
const finishBadge  = $("finish-badge");

/* ---------- Three.js 变量 ---------- */
let scene, camera, renderer;
let droneGroup;
let rainPoints = null;
let groundMesh, homeMarker;
let droneTrail = [];
let trailLine = null;
let treeGroup = null; let treesAreGLB = false;   // 写实树木（程序化 + 可选 GLB）
let farForest = null, undergrowth = null, treeLayout = null, groundGrid = null;
let grassRocks = null;   // 草丛 + 岩石

let lastDronePos = new THREE.Vector3(0, 15, 0);
let clock = new THREE.Clock();
let trailPointCounter = 0;

/* ---------- 无人机模型 ---------- */
// 优先加载真实 GLB 模型 (amvlab/aircraft-models/drone_nologo.glb)
// 加载失败则回退到程序化建模
let droneModelIsGLB = false;
let glbPropellerNodes = [];  // GLB 中需要旋转的螺旋桨节点

function buildDroneModel() {
  // 程序化回退模型
  const g = new THREE.Group();

  // 机身
  const bodyGeo = new THREE.BoxGeometry(1.2, 0.5, 1.2);
  const bodyMat = new THREE.MeshPhongMaterial({ color: DRONE_COLORS.body, shininess: 60 });
  const body = new THREE.Mesh(bodyGeo, bodyMat);
  g.add(body);

  // 四个机臂（X 形）
  const armLen = 1.8, armW = 0.15;
  const armGeo = new THREE.BoxGeometry(armLen, 0.12, armW);
  const armMat = new THREE.MeshPhongMaterial({ color: DRONE_COLORS.arm });
  const armAngles = [45, 135, 225, 315];

  for (const angle of armAngles) {
    const rad = angle * Math.PI / 180;
    const arm = new THREE.Mesh(armGeo, armMat);
    arm.position.set(Math.cos(rad) * armLen / 2, 0, Math.sin(rad) * armLen / 2);
    arm.rotation.y = -rad;
    g.add(arm);

    // 电机
    const motorGeo = new THREE.CylinderGeometry(0.12, 0.15, 0.25, 12);
    const motorMat = new THREE.MeshPhongMaterial({ color: DRONE_COLORS.motor });
    const motor = new THREE.Mesh(motorGeo, motorMat);
    motor.position.set(Math.cos(rad) * armLen, 0.15, Math.sin(rad) * armLen);
    g.add(motor);

    // 螺旋桨
    const propGeo = new THREE.BoxGeometry(1.0, 0.03, 0.1);
    const propMat = new THREE.MeshPhongMaterial({
      color: DRONE_COLORS.prop, transparent: true, opacity: 0.7,
    });
    const prop = new THREE.Mesh(propGeo, propMat);
    prop.position.copy(motor.position).add(new THREE.Vector3(0, 0.18, 0));
    prop.userData.spinSpeed = 10 + Math.random() * 2;
    prop.userData.spinPhase = Math.random() * Math.PI * 2;
    prop.name = "prop";
    g.add(prop);

    // 状态灯
    const lightGeo = new THREE.SphereGeometry(0.06, 8, 8);
    const lightMat = new THREE.MeshBasicMaterial({
      color: angle < 180 ? 0x33ff66 : DRONE_COLORS.light
    });
    const light = new THREE.Mesh(lightGeo, lightMat);
    light.position.set(Math.cos(rad) * armLen, 0.05, Math.sin(rad) * armLen);
    g.add(light);
  }

  // GPS 天线
  const gpsGeo = new THREE.CylinderGeometry(0.2, 0.2, 0.05, 16);
  const gpsMat = new THREE.MeshPhongMaterial({ color: 0x889999 });
  const gps = new THREE.Mesh(gpsGeo, gpsMat);
  gps.position.y = 0.3;
  g.add(gps);

  // 底部摄像头
  const camGeo = new THREE.SphereGeometry(0.15, 12, 12);
  const camMat = new THREE.MeshPhongMaterial({ color: 0x111122 });
  const cam = new THREE.Mesh(camGeo, camMat);
  cam.position.y = -0.3;
  g.add(cam);

  g.scale.set(0.6, 0.6, 0.6);
  return g;
}

// 加载 GLB 模型，成功则替换 droneGroup
function loadGLBDrone(onSuccess, onFail) {
  const loader = new THREE.GLTFLoader();
  loader.load(
    "/static/models/drone_nologo.glb",
    (gltf) => {
      const model = gltf.scene;
      // 自动计算包围盒，归一化缩放使模型约 4 单位宽
      const box = new THREE.Box3().setFromObject(model);
      const size = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z);
      const targetSize = 4.0;
      const scale = maxDim > 0 ? targetSize / maxDim : 1;
      model.scale.set(scale, scale, scale);
      // 居中：把包围盒中心移到 (0,15,0)
      const center = box.getCenter(new THREE.Vector3());
      model.position.set(-center.x * scale + 0, 15 - center.y * scale, -center.z * scale + 0);

      // 收集可旋转的螺旋桨节点（名称含 prop/rotor/blade/spinner/propeller）
      model.traverse(obj => {
        const n = (obj.name || "").toLowerCase();
        if (obj.isMesh && (n.includes("prop") || n.includes("rotor") || n.includes("blade") || n.includes("spinner"))) {
          glbPropellerNodes.push(obj);
        }
      });

      scene.remove(droneGroup);
      droneGroup = model;
      droneModelIsGLB = true;
      lastDronePos.copy(model.position);
      scene.add(model);
      logFrontend(`GLB 模型加载成功 (maxDim=${maxDim.toFixed(2)}, scale=${scale.toFixed(3)})，propeller 节点: ${glbPropellerNodes.length}`);
      onSuccess && onSuccess();
    },
    undefined,
    (err) => {
      console.warn("GLB 加载失败，使用程序化模型:", err);
      logFrontend("GLB 加载失败，使用程序化模型回退", "WARN");
      onFail && onFail();
    }
  );
}

/* ---------- 雨粒子系统（以无人机为中心的局部坐标）---------- */
const RAIN_COUNT = 2000;
let rainVelocities;

function buildRainSystem() {
  const geo = new THREE.BufferGeometry();
  const positions = new Float32Array(RAIN_COUNT * 3);
  rainVelocities = new Float32Array(RAIN_COUNT * 3);

  for (let i = 0; i < RAIN_COUNT; i++) {
    // 以 (0,0,0) 为中心的局部坐标，初始时由 _updateRain 设置到无人机周围
    positions[i * 3]     = (Math.random() - 0.5) * 100;
    positions[i * 3 + 1] = Math.random() * 45;
    positions[i * 3 + 2] = (Math.random() - 0.5) * 100;
    rainVelocities[i * 3]     = (Math.random() - 0.5) * 0.5;
    rainVelocities[i * 3 + 1] = -(8 + Math.random() * 4);
    rainVelocities[i * 3 + 2] = (Math.random() - 0.5) * 0.5;
  }

  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));

  const mat = new THREE.PointsMaterial({
    color: 0x88bbee,
    size: 0.15,
    transparent: true,
    opacity: 0.7,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });

  rainPoints = new THREE.Points(geo, mat);
  rainPoints.visible = false;
  scene.add(rainPoints);
}

function updateRain() {
  if (!rainPoints || !rainPoints.visible) return;
  const pos = rainPoints.geometry.attributes.position.array;
  const dx = droneGroup.position.x;
  const dy = droneGroup.position.y;
  const dz = droneGroup.position.z;

  for (let i = 0; i < RAIN_COUNT; i++) {
    pos[i * 3]     += rainVelocities[i * 3];
    pos[i * 3 + 1] += rainVelocities[i * 3 + 1];
    pos[i * 3 + 2] += rainVelocities[i * 3 + 2];

    // 雨点到达地面（y < 0）或远离无人机超过 80m 时，在无人机上方重新生成
    const distX = pos[i * 3] - dx;
    const distZ = pos[i * 3 + 2] - dz;
    if (pos[i * 3 + 1] < 0 || distX * distX + distZ * distZ > 6400) {
      pos[i * 3]     = dx + (Math.random() - 0.5) * 100;
      pos[i * 3 + 1] = dy + 30 + Math.random() * 20;
      pos[i * 3 + 2] = dz + (Math.random() - 0.5) * 100;
    }
  }
  rainPoints.geometry.attributes.position.needsUpdate = true;
}

/* ---------- 地面场景 ---------- */
function buildGround() {
  const gsz = (typeof TREE_CONFIG !== "undefined" && TREE_CONFIG.forestGroundSize) ? TREE_CONFIG.forestGroundSize : 400;
  const groundGeo = new THREE.PlaneGeometry(gsz, gsz, 40, 40);
  const groundMat = new THREE.MeshPhongMaterial({
    color: 0x0f2a14, side: THREE.DoubleSide,
    transparent: true, opacity: 0.92,
  });
  groundMesh = new THREE.Mesh(groundGeo, groundMat);
  groundMesh.rotation.x = -Math.PI / 2;
  groundMesh.position.y = 0;
  scene.add(groundMesh);

  groundGrid = new THREE.GridHelper(gsz, 60, 0x1a3a20, 0x0f2a14);
  groundGrid.position.y = 0.01;
  scene.add(groundGrid);

  // home 标记
  const homeGeo = new THREE.CylinderGeometry(2, 2, 0.3, 24);
  const homeMat = new THREE.MeshBasicMaterial({ color: 0x44ff88, transparent: true, opacity: 0.5 });
  homeMarker = new THREE.Mesh(homeGeo, homeMat);
  homeMarker.position.set(0, 0.15, 0);
  scene.add(homeMarker);

  const homeGlow = new THREE.PointLight(0x44ff88, 2, 15);
  homeGlow.position.set(0, 2, 0);
  scene.add(homeGlow);
}

/* ---------- 树木系统 v2 · 密集真实树林（参考现实温带混交林 + InstancedMesh 性能）---------- */
// 现实森林：落叶 60% + 针叶 40%、树木间距 1.5~3m、冠层密度 50%+、含下木灌木、
// 远景林缘多层剪影、森林薄雾营造纵深。近景树用 InstancedMesh（1 棵 = 1 实例），
// 远景/下木也用 InstancedMesh，总 draw call < 24，3000 棵仍 60fps（实例化）。
const TREE_CONFIG = {
  forestGroundSize: 1600,      // 地图 800 -> 1600m（256 公顷，背景全树林）
  forestCount: 3000,          // 树木 -> 3000（密集混交林，地图背景全树）
  treeHeights: [7, 24],       // 树高 7~24m（林冠层次：矮 7 / 中 12 / 大 24）
  canopyRadius: [2.2, 6.0],   // 冠半径（加宽，林冠更密）
  clusterCount: 240,         // 现实森林：树木成群（~240 簇心，每簇 10~16 棵，大地图密簇）
  clusterRadius: [2.5, 5.5], // 簇内树木散落半径
  clusterGap: [9, 16],       // 簇心间距下限
  seedOffset: 0.35,
  trunkColor: 0x6b4f3a, trunkColor2: 0x4a3426,
  leafColor:  0x2f7a3f, leafColor2: 0x3f9a4f, leafColor3: 0x54a862,
  pineLeafColor: 0x1f5f2f, pineLeafColor2: 0x2f7a3f,
  trunkSegs: 8, leafSegs: 16,
  mixRatio: 0.6,             // 60% 落叶 + 40% 针叶（现实混交林比例）
  glbDir: "/static/models/scenery/",  // 用户可放 GLB 替换（/static/ 路径）
  glbTargetHeight: 14.0,
  // 远景剪影树林层（8 圈，越远越暗+被雾吞，营造"无边树林"纵深）
  farRings: [ {dist:380, count:140, h:30, c:0x1a2a20},
              {dist:500, count:170, h:42, c:0x131f18},
              {dist:650, count:200, h:54, c:0x0d1510},
              {dist:800, count:240, h:66, c:0x080d0a},
              {dist:1000, count:280, h:78, c:0x060a08},
              {dist:1200, count:320, h:90, c:0x040806},
              {dist:1400, count:360, h:102, c:0x020604},
              {dist:1600, count:400, h:114, c:0x010302} ],
  // 雾（现实森林薄雾感；地图 1600m 雾扩展到 900m）
  fogColor: 0x0e1a14, fogNear: 80, fogFar: 900,
};

/* 确定性伪随机（布局可复现，每次启动一致） */
function _seededRandom(seed){
  const x = Math.sin(seed) * 43758.5453;
  return x - Math.floor(x);
}

/* 生成树林布局（现实森林簇分布 + 空间网格 O(n) 邻居检查）：
   现实森林树木成群（林块）：先生成 ~120 个簇心（间距 9~16m，避 home 区+航线走廊），
   每簇在 2.5~5.5m 半径内散射 10~16 棵树（簇内间距 1.5m），总棵数取 forestCount 上限。
   网格 cell=2m，邻居检查只看 3x3 相邻 cell，O(n) 不随密度卡。 */
function _generateTreeLayout(count, groundSize, seed){
  const half = groundSize/2, pad = 24;
  const lo = -half + pad, hi = half - pad;
  const CC = TREE_CONFIG.clusterCount || 120;
  const CELL = 2.0;
  const grid = new Map();
  const out = [];
  function tryPlace(x, z, h, r, rot, pine){
    if (Math.sqrt(x*x + z*z) < 12) return false;
    if (Math.abs(x) < 40 && Math.abs(z) < 160) return false;
    const cx = Math.floor(x/CELL) + 1000, cz = Math.floor(z/CELL) + 1000;
    for (let ax = -1; ax <= 1; ax++){
      for (let az = -1; az <= 1; az++){
        const k = (cx+ax) + "," + (cz+az);
        const arr = grid.get(k);
        if (!arr) continue;
        for (const idx of arr){
          const t = out[idx];
          const dx = t.x - x, dz = t.z - z;
          if (dx*dx + dz*dz < 2.25){ return false; }
        }
      }
    }
    out.push({ x, z, h, r, rot, pine });
    const idx = out.length - 1;
    const k = cx + "," + cz;
    if (!grid.has(k)) grid.set(k, []);
    grid.get(k).push(idx);
    return true;
  }
  const clusters = [];
  let cg = 0;
  while (clusters.length < CC && cg < CC * 60){
    cg++;
    const cx0 = lo + _seededRandom(cg*1.31 + seed) * (hi - lo);
    const cz0 = lo + _seededRandom(cg*2.93 + seed + 0.4) * (hi - lo);
    if (Math.sqrt(cx0*cx0 + cz0*cz0) < 14) continue;
    if (Math.abs(cx0) < 45 && Math.abs(cz0) < 170) continue;
    let ok = true;
    for (const c of clusters){
      const dx = c.x - cx0, dz = c.z - cz0;
      if (dx*dx + dz*dz < 81){ ok = false; break; }
    }
    if (!ok) continue;
    clusters.push({ x: cx0, z: cz0, per: 10 + Math.floor(_seededRandom(cg*4.7+seed)*7) });
  }
  let placed = 0;
  for (const c of clusters){
    if (placed >= count) break;
    for (let k = 0; k < c.per && placed < count; k++){
      const a = _seededRandom(cg*0.51 + c.x*0.13 + k*7.7 + seed) * Math.PI * 2;
      const rr = TREE_CONFIG.clusterRadius[0] + _seededRandom(cg*0.71 + c.z*0.17 + k*3.3 + seed) * (TREE_CONFIG.clusterRadius[1] - TREE_CONFIG.clusterRadius[0]);
      const x = c.x + Math.cos(a)*rr*0.6;
      const z = c.z + Math.sin(a)*rr*0.6;
      if (x < lo || x > hi || z < lo || z > hi) continue;
      const h = TREE_CONFIG.treeHeights[0] + _seededRandom(cg*3.3 + c.x + k*1.7 + seed)*(TREE_CONFIG.treeHeights[1]-TREE_CONFIG.treeHeights[0]);
      const r = TREE_CONFIG.canopyRadius[0] + _seededRandom(cg*4.9 + c.z + k*1.3 + seed)*(TREE_CONFIG.canopyRadius[1]-TREE_CONFIG.canopyRadius[0]);
      const isPine = _seededRandom(cg*5.7 + c.x + c.z + k*0.7 + seed) > TREE_CONFIG.mixRatio;
      if (tryPlace(x, z, h, r, _seededRandom(cg*6.1 + k*2.3 + seed)*Math.PI*2, isPine)){ placed++; }
    }
  }
  let sg = 0;
  while (placed < count && sg < (count - placed) * 80){
    sg++;
    const x = lo + _seededRandom(sg*1.13 + seed + 50) * (hi - lo);
    const z = lo + _seededRandom(sg*2.71 + seed + 50.5) * (hi - lo);
    const h = TREE_CONFIG.treeHeights[0] + _seededRandom(sg*3.3+seed+51)*(TREE_CONFIG.treeHeights[1]-TREE_CONFIG.treeHeights[0]);
    const r = TREE_CONFIG.canopyRadius[0] + _seededRandom(sg*4.9+seed+52)*(TREE_CONFIG.canopyRadius[1]-TREE_CONFIG.canopyRadius[0]);
    const isPine = _seededRandom(sg*5.7+seed+53) > TREE_CONFIG.mixRatio;
    if (tryPlace(x, z, h, r, _seededRandom(sg*6.1+seed+54)*Math.PI*2, isPine)) placed++;
  }
  return out;
}

/* 近景树林：InstancedMesh（树干 + 落叶两层冠 + 针叶三层锥 + 树影） */
function buildForestTrees(layout, seed){
  if (treeGroup){ scene.remove(treeGroup); treeGroup = null; }
  treeGroup = new THREE.Group();
  treeLayout = layout;
  const n = layout.length;
  const decCount = layout.filter(t => !t.pine).length;
  const pineCount = n - decCount;
  const trunkGeo = new THREE.CylinderGeometry(0.5, 0.9, 1, TREE_CONFIG.trunkSegs, 1, true);
  const trunkMat = new THREE.MeshPhongMaterial({ color: TREE_CONFIG.trunkColor, shininess:8, flatShading:true });
  const trunks = new THREE.InstancedMesh(trunkGeo, trunkMat, n);
  const decGeo = new THREE.SphereGeometry(1, TREE_CONFIG.leafSegs, Math.max(10, Math.floor(TREE_CONFIG.leafSegs*0.8)));
  const decA = new THREE.InstancedMesh(decGeo,
    new THREE.MeshPhongMaterial({ color: TREE_CONFIG.leafColor,  shininess:12, flatShading:true, transparent:true, opacity:0.95 }), decCount);
  const decB = new THREE.InstancedMesh(decGeo,
    new THREE.MeshPhongMaterial({ color: TREE_CONFIG.leafColor2, shininess:14, flatShading:true, transparent:true, opacity:0.9 }), decCount);
  const pineGeo = new THREE.ConeGeometry(1, 1, 6);
  const p0 = new THREE.InstancedMesh(pineGeo, new THREE.MeshPhongMaterial({ color: TREE_CONFIG.pineLeafColor,   shininess:8, flatShading:true, transparent:true, opacity:0.95 }), pineCount);
  const p1 = new THREE.InstancedMesh(pineGeo, new THREE.MeshPhongMaterial({ color: TREE_CONFIG.pineLeafColor2,  shininess:8, flatShading:true, transparent:true, opacity:0.9 }), pineCount);
  const p2 = new THREE.InstancedMesh(pineGeo, new THREE.MeshPhongMaterial({ color: TREE_CONFIG.pineLeafColor2,  shininess:8, flatShading:true, transparent:true, opacity:0.85 }), pineCount);
  const M = new THREE.Matrix4(), Q = new THREE.Quaternion(), P = new THREE.Vector3(), S = new THREE.Vector3();
  const yAxis = new THREE.Vector3(0,1,0);
  let di = 0, pi = 0;
  /* 现实森林改进：逐棵颜色微变（落叶 4 色阶 / 针叶 3 色阶 / 树干 3 色阶）+ 树干倾斜 2~5 度 */
  const leafPal = [new THREE.Color(0x2f7a3f), new THREE.Color(0x3f9a4f), new THREE.Color(0x54a862), new THREE.Color(0x6fbf7f)];
  const pinePal = [new THREE.Color(0x1f5f2f), new THREE.Color(0x2f7a3f), new THREE.Color(0x3a8a4a)];
  const trunkPal = [new THREE.Color(0x6b4f3a), new THREE.Color(0x5a3f2a), new THREE.Color(0x7a5f4a)];
  const qTmp = new THREE.Quaternion(), zAxis = new THREE.Vector3(0,0,1);
  layout.forEach((t, i) => {
    const trunkH = t.h * 0.45, canopyH = t.h - trunkH;
    const tiltDeg = 2 + _seededRandom(i*9.1+seed)*3.0;
    const tilt = tiltDeg * (_seededRandom(i*9.7+seed)>0.5?1:-1) * (Math.PI/180);
    qTmp.setFromAxisAngle(yAxis, t.rot);
    qTmp.premultiply(new THREE.Quaternion().setFromAxisAngle(zAxis, tilt));
    P.set(t.x, trunkH/2, t.z); S.set(t.r*0.45, trunkH, t.r*0.45);
    M.compose(P, qTmp, S);
    trunks.setMatrixAt(i, M);
    trunks.setColorAt(i, trunkPal[i % 3]);
    if (!t.pine){
      const cy = trunkH + canopyH*0.5;
      decA.setColorAt(di, leafPal[i % 4]);
      decB.setColorAt(di, leafPal[(i+1) % 4]);
      P.set(t.x, cy, t.z); S.set(t.r, canopyH*0.55, t.r);
      Q.setFromAxisAngle(yAxis, t.rot+0.3); M.compose(P,Q,S); decA.setMatrixAt(di, M);
      P.set(t.x, cy+canopyH*0.4, t.z); S.set(t.r*0.8, canopyH*0.4, t.r*0.8); M.compose(P,Q,S); decB.setMatrixAt(di, M);
      di++;
    } else {
      const L = [
        {y: trunkH*0.5, sy: canopyH*0.5,  sx: t.r},
        {y: trunkH + canopyH*0.45, sy: canopyH*0.4,  sx: t.r*0.8},
        {y: trunkH + canopyH*0.75, sy: canopyH*0.35, sx: t.r*0.55},
      ];
      const pM = [p0,p1,p2];
      L.forEach((d2,k) => { P.set(t.x, d2.y + d2.sy/2, t.z); S.set(d2.sx, d2.sy, d2.sx);
        Q.setFromAxisAngle(yAxis, t.rot + k*0.6); M.compose(P,Q,S);
        pM[k].setColorAt(pi, pinePal[(i+k) % 3]);
        pM[k].setMatrixAt(pi, M); });
      pi++;
    }
  });
  trunks.instanceMatrix.needsUpdate = true;
  [decA,decB,p0,p1,p2].forEach(m => { if(m.count) m.instanceMatrix.needsUpdate = true; });
  if (trunks.instanceColor) trunks.instanceColor.needsUpdate = true;
  [decA,decB,p0,p1,p2].forEach(m => { if(m.instanceColor) m.instanceColor.needsUpdate = true; });
  // 树影（实例化圆片，贴地）
  const shGeo = new THREE.CircleGeometry(1, 16);
  const shMat = new THREE.MeshBasicMaterial({ color:0, transparent:true, opacity:0.18, depthWrite:false, side:THREE.DoubleSide });
  const shadows = new THREE.InstancedMesh(shGeo, shMat, n);
  layout.forEach((t, i) => { P.set(t.x, 0.02, t.z); S.set(t.r*1.1, 1, t.r*1.1);
    Q.identity(); M.compose(P,Q,S); shadows.setMatrixAt(i, M); });
  shadows.rotation.x = -Math.PI/2;
  shadows.instanceMatrix.needsUpdate = true;
  /* 落叶层：每树 1 个浅绿贴地圆片（现实森林林下落叶） */
  const leafGeo = new THREE.CircleGeometry(1, 12);
  const leafMat = new THREE.MeshBasicMaterial({ color:0x4a6f35, transparent:true, opacity:0.22, depthWrite:false, side:THREE.DoubleSide });
  const leafLayer = new THREE.InstancedMesh(leafGeo, leafMat, n);
  layout.forEach((t, i) => { P.set(t.x, 0.03, t.z); S.set(t.r*1.2, 1, t.r*1.2);
    Q.identity(); M.compose(P,Q,S); leafLayer.setMatrixAt(i, M); });
  leafLayer.rotation.x = -Math.PI/2;
  leafLayer.instanceMatrix.needsUpdate = true;
  treeGroup.add(trunks, decA, decB, p0, p1, p2, shadows, leafLayer);
  scene.add(treeGroup);
  logFrontend("树林：近景 " + n + " 棵（落叶 " + decCount + " / 针叶 " + pineCount + "，InstancedMesh 6+1 draw call）", "INFO");
}

/* 远景剪影树林（InstancedMesh 4 draw call：3 层针叶锥 + 阔叶球，越远越暗+雾吞） */
function buildFarForestRings(){
  if (farForest){ scene.remove(farForest); farForest = null; }
  farForest = new THREE.Group();
  const total = TREE_CONFIG.farRings.reduce((a,r) => a+r.count, 0);
  const totalPine = Math.ceil(total/2), totalDec = total - totalPine;
  const coneGeo = new THREE.ConeGeometry(1, 1, 5);
  const sphereGeo = new THREE.SphereGeometry(1, 7, 5);
  const midRing = TREE_CONFIG.farRings[Math.floor(TREE_CONFIG.farRings.length/2)];
  const coneMat = new THREE.MeshPhongMaterial({ color:midRing.c, flatShading:true, transparent:true, opacity:0.72 });
  const decMat  = new THREE.MeshPhongMaterial({ color:midRing.c, flatShading:true, transparent:true, opacity:0.66 });
  const c0 = new THREE.InstancedMesh(coneGeo, coneMat, totalPine);
  const c1 = new THREE.InstancedMesh(coneGeo, coneMat, totalPine);
  const c2 = new THREE.InstancedMesh(coneGeo, coneMat, totalPine);
  const dec = new THREE.InstancedMesh(sphereGeo, decMat, totalDec);
  const M = new THREE.Matrix4(), Q = new THREE.Quaternion(), P = new THREE.Vector3(), S = new THREE.Vector3();
  const yAxis = new THREE.Vector3(0,1,0);
  let pi = 0, di2 = 0;
  TREE_CONFIG.farRings.forEach((ring, ri) => {
    for (let i=0;i<ring.count;i++){
      const a = (i/ring.count)*Math.PI*2 + _seededRandom(i*1.7+ri)*0.5;
      const jitter = 0.85 + _seededRandom(i*3.1+ri)*0.3;
      const x = Math.cos(a)*ring.dist*jitter, z = Math.sin(a)*ring.dist*jitter;
      const isPine = (i%2===0);
      if (isPine){
        const layers = [ {dy:0.22, sy:0.50, sx:1.0}, {dy:0.55, sy:0.42, sx:0.75}, {dy:0.82, sy:0.34, sx:0.5} ];
        const pM = [c0,c1,c2];
        layers.forEach((L,k) => {
          const sc = ring.h*0.32*L.sx;
          P.set(x, ring.h*L.dy, z); S.set(sc, ring.h*L.sy, sc);
          Q.setFromAxisAngle(yAxis, _seededRandom(i*7.3+ri)*6.28); M.compose(P,Q,S);
          pM[k].setMatrixAt(pi, M);
        });
        pi++;
      } else {
        const sc = ring.h*0.32;
        P.set(x, ring.h*0.55, z); S.set(sc, ring.h*0.45, sc);
        Q.identity(); M.compose(P,Q,S);
        dec.setMatrixAt(di2++, M);
      }
    }
  });
  c0.count = pi; c1.count = pi; c2.count = pi;
  [c0,c1,c2].forEach(m => m.instanceMatrix.needsUpdate = true);
  dec.count = di2; dec.instanceMatrix.needsUpdate = true;
  farForest.add(c0,c1,c2,dec);
  scene.add(farForest);
  logFrontend("树林：远景剪影 " + total + " 棵（4 圈 InstancedMesh，越远越暗+雾吞，仅 4 draw call）", "INFO");
}

/* 下木灌木（现实森林地面层：矮灌木/蕨类点缀，InstancedMesh 2 种材质） */
function buildUndergrowth(layout){
  if (undergrowth){ scene.remove(undergrowth); undergrowth = null; }
  undergrowth = new THREE.Group();
  const bushGeo = new THREE.SphereGeometry(1, 8, 6);
  const m1 = new THREE.MeshPhongMaterial({ color:0x2a5f33, shininess:6, flatShading:true, transparent:true, opacity:0.9 });
  const m2 = new THREE.MeshPhongMaterial({ color:0x3a7a45, shininess:8, flatShading:true, transparent:true, opacity:0.85 });
  const bushA = new THREE.InstancedMesh(bushGeo, m1, 720);
  const bushB = new THREE.InstancedMesh(bushGeo, m2, 720);
  const M = new THREE.Matrix4(), Q = new THREE.Quaternion(), P = new THREE.Vector3(), S = new THREE.Vector3();
  const yAxis = new THREE.Vector3(0,1,0);
  let ai = 0, bi = 0;
  for (let i=0;i<1800 && layout.length;i++){
    const t = layout[i % layout.length];
    const off = _seededRandom(i*2.3) * Math.PI * 2;
    const dist = 1.5 + _seededRandom(i*3.7) * 3.0;
    const x = t.x + Math.cos(off)*dist, z = t.z + Math.sin(off)*dist;
    if (Math.sqrt(x*x+z*z) < 12) continue;
    if (Math.abs(x) < 40 && Math.abs(z) < 160) continue;
    const s = 0.6 + _seededRandom(i*5.1)*0.9;
    P.set(x, s*0.3, z); S.set(s, s*0.6, s);
    Q.setFromAxisAngle(yAxis, _seededRandom(i*7.7)*Math.PI*2); M.compose(P,Q,S);
    if (i%2===0){ if(ai<720) bushA.setMatrixAt(ai++, M); }
    else         { if(bi<720) bushB.setMatrixAt(bi++, M); }
  }
  bushA.count = ai; bushB.count = bi;
  bushA.instanceMatrix.needsUpdate = true; bushB.instanceMatrix.needsUpdate = true;
  undergrowth.add(bushA, bushB);
  scene.add(undergrowth);
  logFrontend("下木灌木：" + (ai+bi) + " 簇（InstancedMesh 2 draw call）", "INFO");
}

/* 草地草丛 + 岩石（现实森林地面层：草/石块点缀，InstancedMesh 3 draw call） */
function buildGrassAndRocks(layout, seed){
  if (grassRocks){ scene.remove(grassRocks); grassRocks = null; }
  grassRocks = new THREE.Group();
  const gsz = TREE_CONFIG.forestGroundSize, half = gsz/2;
  const M = new THREE.Matrix4(), Q = new THREE.Quaternion(), P = new THREE.Vector3(), S = new THREE.Vector3();
  const yAxis = new THREE.Vector3(0,1,0);
  const grassGeo = new THREE.ConeGeometry(0.15, 0.5, 4);
  const gm1 = new THREE.MeshPhongMaterial({ color:0x3a6f35, shininess:4, flatShading:true });
  const gm2 = new THREE.MeshPhongMaterial({ color:0x4a8f45, shininess:4, flatShading:true });
  const G_COUNT = 1500;
  const gA = new THREE.InstancedMesh(grassGeo, gm1, G_COUNT);
  const gB = new THREE.InstancedMesh(grassGeo, gm2, G_COUNT);
  let gi = 0, guard = 0;
  while (gi < G_COUNT*2 && guard < G_COUNT*40){
    guard++;
    const x = _seededRandom(guard*0.71 + (seed||0.35))*gsz - half;
    const z = _seededRandom(guard*1.13 + (seed||0.35))*gsz - half;
    if (Math.sqrt(x*x+z*z) < 8) continue;
    if (Math.abs(x) < 35 && Math.abs(z) < 150) continue;
    const s = 0.7 + _seededRandom(guard*2.3 + (seed||0.35))*0.8;
    P.set(x, 0.25*s, z); S.set(s, s, s);
    Q.setFromAxisAngle(yAxis, _seededRandom(guard*3.7 + (seed||0.35))*6.28); M.compose(P,Q,S);
    if (guard % 2 === 0){ gA.setMatrixAt(gi % G_COUNT, M); } else { gB.setMatrixAt(gi % G_COUNT, M); }
    gi++;
  }
  gA.count = Math.min(G_COUNT, Math.floor(gi/2)); gB.count = Math.min(G_COUNT, gi - Math.floor(gi/2));
  gA.instanceMatrix.needsUpdate = true; gB.instanceMatrix.needsUpdate = true;
  const rockGeo = new THREE.OctahedronGeometry(0.4, 0);
  const rm = new THREE.MeshPhongMaterial({ color:0x5a5a60, shininess:6, flatShading:true });
  const R_COUNT = 150;
  const rocks = new THREE.InstancedMesh(rockGeo, rm, R_COUNT);
  let ri = 0, rg = 0;
  while (ri < R_COUNT && rg < R_COUNT*30){
    rg++;
    const x = _seededRandom(rg*5.1 + (seed||0.35))*gsz - half;
    const z = _seededRandom(rg*6.7 + (seed||0.35))*gsz - half;
    if (Math.sqrt(x*x+z*z) < 10) continue;
    if (Math.abs(x) < 40 && Math.abs(z) < 160) continue;
    const s = 0.4 + _seededRandom(rg*7.3 + (seed||0.35))*0.8;
    P.set(x, 0.15*s, z); S.set(s, s*0.6, s);
    Q.setFromAxisAngle(yAxis, _seededRandom(rg*8.9 + (seed||0.35))*6.28); M.compose(P,Q,S);
    rocks.setMatrixAt(ri++, M);
  }
  rocks.count = ri; rocks.instanceMatrix.needsUpdate = true;
  grassRocks.add(gA, gB, rocks);
  scene.add(grassRocks);
  logFrontend("地面层：草丛 " + (gA.count+gB.count) + " 簇 + 岩石 " + ri + " 块（InstancedMesh 3 draw call）", "INFO");
}

/* GLB 接入（可选）：放入 models/scenery/tree.glb 等则克隆到布局位替换近景程序化树 */
function loadSceneryGLB(onDone){
  if (typeof THREE === "undefined" || !THREE.GLTFLoader){ onDone && onDone(false); return; }
  const cands = ["tree.glb","trees.glb","tree_realistic.glb","oak.glb","pine.glb","forest.glb"];
  let idx = 0;
  function tryNext(){
    if (idx >= cands.length){ onDone && onDone(false); return; }
    const url = TREE_CONFIG.glbDir + cands[idx];
    const loader = new THREE.GLTFLoader();
    loader.load(url, (gltf) => {
      const model = gltf.scene;
      const box = new THREE.Box3().setFromObject(model);
      const size = box.getSize(new THREE.Vector3());
      const h = Math.max(size.y, 0.1);
      const s = TREE_CONFIG.glbTargetHeight / h;
      model.scale.set(s,s,s);
      treesAreGLB = true;
      const layout = treeLayout || _generateTreeLayout(TREE_CONFIG.forestCount, TREE_CONFIG.forestGroundSize, TREE_CONFIG.seedOffset);
      layout.forEach((t, i) => {
        const inst = model.clone();
        inst.position.set(t.x, 0, t.z); inst.rotation.y = t.rot;
        treeGroup.add(inst);
      });
      logFrontend("树林：GLB 加载成功 " + cands[idx] + "，克隆到 " + layout.length + " 个布局位 (h=" + h.toFixed(2) + ", scale=" + s.toFixed(3) + ")");
      onDone && onDone(true);
    }, undefined, () => { idx++; tryNext(); });
  }
  tryNext();
}

/* 入口：程序化密集树林 + 远景 + 下木 + 雾；再异步探测 GLB 替换近景 */
function buildSceneryTreesAuto(){
  const layout = _generateTreeLayout(TREE_CONFIG.forestCount, TREE_CONFIG.forestGroundSize, TREE_CONFIG.seedOffset);
  buildForestTrees(layout, TREE_CONFIG.seedOffset);
  buildUndergrowth(layout);
  buildGrassAndRocks(layout, TREE_CONFIG.seedOffset);
  buildFarForestRings();
  logFrontend("树林升级：地面 " + TREE_CONFIG.forestGroundSize + "m / 近景 " + layout.length +
    " 棵（密集混交林）+ 远景 " + TREE_CONFIG.farRings.reduce((a,r)=>a+r.count,0) +
    " 棵剪影 + 下木灌木 + 森林薄雾", "INFO");
  if (typeof THREE !== "undefined" && THREE.GLTFLoader){
    loadSceneryGLB((ok) => { if(!ok) logFrontend("树林：未发现本地 GLB，保持程序化密集树林", "INFO"); });
  }
}

/* ---------- 飞行轨迹 ---------- */
function buildTrail() {
  droneTrail = [];
  if (trailLine) { scene.remove(trailLine); trailLine.geometry.dispose(); trailLine = null; }
}

function addTrailPoint(pos) {
  droneTrail.push(pos.clone());
  if (droneTrail.length > 400) droneTrail.shift();
  if (droneTrail.length >= 2) {
    const geo = new THREE.BufferGeometry().setFromPoints(droneTrail);
    const mat = new THREE.LineBasicMaterial({ color: 0x44aaff, transparent: true, opacity: 0.5 });
    trailLine = new THREE.Line(geo, mat);
    scene.add(trailLine);
  }
}

/* ---------- Three.js 初始化 ---------- */
function initThree() {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setClearColor(0x0a0e1a);

  scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x0a0e1a, 80, 400);

  camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 3000);
  camera.position.set(0, 15, 30);
  camera.lookAt(0, 5, 0);

  scene.add(new THREE.AmbientLight(0x334466, 0.6));
  const dirLight = new THREE.DirectionalLight(0x8899bb, 0.8);
  dirLight.position.set(30, 50, 20);
  scene.add(dirLight);
  const pointLight = new THREE.PointLight(0x4488ff, 1, 100);
  pointLight.position.set(0, 30, 0);
  scene.add(pointLight);

  buildGround();
  buildSceneryTreesAuto();   // 写实树木（程序化 + 可选 GLB）
  droneGroup = buildDroneModel();   // 先放程序化模型，随后尝试加载 GLB 替换
  droneGroup.position.set(0, 15, 0);
  scene.add(droneGroup);
  buildRainSystem();
  buildTrail();

  // 尝试加载真实 GLB 模型（异步）
  loadGLBDrone();

  window.addEventListener("resize", onResize);
}

function onResize() {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
}

/* ---------- 场景更新 ---------- */
function updateScene(simTime) {
  // 旋转螺旋桨
  const t = clock.getElapsedTime();
  if (droneModelIsGLB && glbPropellerNodes.length > 0) {
    glbPropellerNodes.forEach((node, i) => {
      node.rotation.y = t * (12 + i) + i;
    });
  } else {
    droneGroup.traverse(obj => {
      if (obj.name === "prop") {
        obj.rotation.y = t * obj.userData.spinSpeed + obj.userData.spinPhase;
      }
    });
  }

  // 雨粒子
  if (state.rainActive) {
    if (!rainPoints.visible) {
      rainPoints.visible = true;
      // 下雨时天空变暗
      scene.fog = new THREE.Fog(0x080a14, 60, 300);
      renderer.setClearColor(0x080a14);
    }
    updateRain();
  } else {
    rainPoints.visible = false;
    scene.fog = new THREE.Fog(0x0a0e1a, 80, 400);
    renderer.setClearColor(0x0a0e1a);
  }

  // 相机跟随无人机（平滑追踪）
  const target = droneGroup.position;
  const camTarget = new THREE.Vector3(target.x * 0.3, target.y + 10, target.z * 0.3 + 25);
  camera.position.lerp(camTarget, 0.05);
  camera.lookAt(target);

  renderer.render(scene, camera);
}

/* ---------- 动画循环 ---------- */
function animationLoop() {
  const dt = clock.getDelta();
  state.lastFrameDt = dt;

  if (state.playing && !state.paused && !state.finished) {
    const frameDt = dt * state.speed;
    state.playTime += frameDt;
    const totalS = state.simData.total_s;

    if (state.playTime >= totalS) {
      state.playTime = totalS;
      onFlightComplete();
    }
    updateDroneFromSimTime(state.playTime, frameDt);
  }

  updateScene(state.playTime);
  requestAnimationFrame(animationLoop);
}

/* ---------- 根据模拟时间更新无人机位置（线性插值）---------- */
function updateDroneFromSimTime(simTime, frameDt) {
  if (!state.simData) return;
  const posSeq = state.simData.position_seq;
  if (posSeq.length === 0) return;

  // 线性插值（0.5s 一步）
  const step = 0.5;
  let idx = Math.floor(simTime / step);
  if (idx >= posSeq.length) idx = posSeq.length - 1;
  const idx1 = idx;
  const idx2 = Math.min(idx + 1, posSeq.length - 1);
  const p1 = posSeq[idx1];
  const p2 = posSeq[idx2];
  const frac = Math.max(0, Math.min(1, (simTime - p1.t) / step));

  const home = state.simData.home;
  // lat/lon 偏移 → 3D 世界坐标（1 度 ≈ 100 单位，可视化比例）
  const latOff = (p1.lat - home.lat) * (1 - frac) + (p2.lat - home.lat) * frac;
  const lonOff = (p1.lon - home.lon) * (1 - frac) + (p2.lon - home.lon) * frac;
  const worldX = latOff * 100;
  const worldZ = lonOff * 100;
  const worldY = 15 + Math.sin(simTime * 0.5) * 0.5;

  // 平滑移动
  lastDronePos.lerp(new THREE.Vector3(worldX, worldY, worldZ), 0.15);
  droneGroup.position.copy(lastDronePos);

  // 轨迹（每 1 秒模拟时间添加一个点）
  trailPointCounter += frameDt;
  if (trailPointCounter >= 1.0) {
    trailPointCounter = 0;
    addTrailPoint(droneGroup.position);
  }

  // HUD: 时间戳
  const totalSec = Math.floor(simTime);
  const hh = String(Math.floor(totalSec / 3600) + 8).padStart(2, "0"); // 模拟从 08:00:00 开始
  const mm = String(Math.floor((totalSec % 3600) / 60)).padStart(2, "0");
  const ss = String(totalSec % 60).padStart(2, "0");
  hudTime.textContent = `⏱ ${hh}:${mm}:${ss}`;

  // HUD: 定位数据
  const dispLat = (home.lat + latOff).toFixed(4);
  const dispLon = (home.lon + lonOff).toFixed(4);
  hudLatlon.textContent = `📍 ${dispLat}, ${dispLon}`;
  hudAlt.textContent = `⬆ ${worldY.toFixed(1)}m (home=${p1.alt}m)`;

  // HUD: 电量（从 pos_seq 取，比计算更准确）
  const battPct = Math.round((p1.battery_pct * (1 - frac)) + (p2.battery_pct * frac));
  hudBattery.textContent = `🔋 ${battPct}%`;

  // 天气/事件状态
  state.rainActive = p1.raining || p2.raining;
  if (state.rainActive) {
    hudEvent.textContent = "🌧 下雨中 · 持续降雨";
  } else {
    const activeEvents = state.simData.events.filter(ev =>
      simTime >= ev.start_s && simTime < ev.start_s + ev.dur_s
    );
    hudEvent.textContent = activeEvents.length > 0
      ? "⚠ " + activeEvents.map(e => e.name_cn).join("、")
      : "";
  }

  // HUD: 模式
  const tick = getNearestTick(simTime);
  if (tick) {
    const modeClass = "mode-" + tick.mode.toLowerCase();
    hudMode.textContent = `模式: ${tick.mode_cn} | ${tick.anomaly_cn}`;
    hudMode.className = `hud-row ${modeClass}`;
  } else {
    hudMode.textContent = "模式: 巡航";
    hudMode.className = "hud-row mode-cruise";
  }

  // 时间轴进度条
  const totalS = state.simData.total_s;
  const pct = (simTime / totalS * 100).toFixed(1);
  timelineFill.style.width = pct + "%";
  timelineLabel.textContent = `${formatSimTime(simTime)} / ${formatSimTime(totalS)}`;
}

function getNearestTick(simTime) {
  const ticks = state.simData.ticks;
  if (!ticks || ticks.length === 0) return null;
  // ticks 的 ts 从 8*3600（08:00:00）开始，simTime 从 0 开始
  const OFFSET = 8 * 3600; // 28800 秒
  let lo = 0, hi = ticks.length - 1, best = null;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const tickSimTime = ticks[mid].ts - OFFSET;
    if (tickSimTime <= simTime) { best = ticks[mid]; lo = mid + 1; }
    else hi = mid - 1;
  }
  return best;
}

function formatSimTime(seconds) {
  const totalSec = Math.floor(seconds);
  const mm = String(Math.floor(totalSec / 60)).padStart(2, "0");
  const ss = String(totalSec % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

/* ---------- 飞行完成 ---------- */
function onFlightComplete() {
  state.finished = true;
  state.playing = false;
  btnBack.classList.remove("hidden");
  finishBadge.classList.remove("hidden");
  hudEvent.textContent = "✅ 任务完成 | 安全降落";
  hudMode.textContent = "模式: 降落";
  hudMode.className = "hud-row mode-mission";
  logFrontend("飞行模拟完成: total_s=" + state.simData.total_s, "INFO");
}

/* ---------- API 调用 ---------- */
async function startSim() {
  const minutes = parseFloat(inputMinutes.value) || 8;
  const seedVal = inputSeed.value.trim();
  const seed = seedVal ? parseInt(seedVal, 10) : null;

  btnStart.disabled = true;
  menuStatus.textContent = "正在运行后端模拟，请稍候...";

  try {
    const url = `/api/sim?minutes=${minutes}` + (seed !== null ? `&seed=${seed}` : "");
    logFrontend(`请求模拟数据: minutes=${minutes}, seed=${seed}`);
    const resp = await fetch(url);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    state.simData = data;

    logFrontend(
      `数据加载完成: events=${data.events.length}, ticks=${data.ticks.length}, ` +
      `pos=${data.position_seq.length}, fingerprint=${data.fingerprint.slice(0, 60)}`
    );

    menuStatus.textContent =
      `已加载：${data.events.length} 个事件，` +
      `${data.ticks.length} 条指令记录，` +
      `${data.position_seq.length} 个位置点`;

    showFlightScreen();
  } catch (e) {
    logFrontend("数据加载失败: " + e.message, "ERROR");
    menuStatus.textContent = "加载失败: " + e.message;
    btnStart.disabled = false;
  }
}

function showFlightScreen() {
  menuScreen.classList.add("hidden");
  flightScreen.classList.remove("hidden");

  state.playTime = 0;
  state.playing = true;
  state.paused = false;
  state.finished = false;
  state.rainActive = false;
  trailPointCounter = 0;

  lastDronePos.set(0, 15, 0);
  // GLB 模型保留加载时的局部中心 offset；程序化模型直接归零
  if (droneModelIsGLB) {
    droneGroup.position.set(0, 15, 0);
  } else {
    droneGroup.position.copy(lastDronePos);
  }
  buildTrail();
  rainPoints.visible = false;

  btnBack.classList.add("hidden");
  finishBadge.classList.add("hidden");
  btnPause.textContent = "⏸ 暂停";
  setSpeed(1);

  clock.getDelta(); // 重置时钟
  if (!state._loopStarted) {
    state._loopStarted = true;
    requestAnimationFrame(animationLoop);
  }
  logFrontend("开始播放动画: total_s=" + state.simData.total_s);
}

function showMenuScreen() {
  state.playing = false;
  flightScreen.classList.add("hidden");
  menuScreen.classList.remove("hidden");
  btnStart.disabled = false;
  menuStatus.textContent = "";
  inputSeed.value = "";
  logFrontend("返回菜单界面");
}

/* ---------- 事件绑定 ---------- */
btnStart.addEventListener("click", startSim);
btnBack.addEventListener("click", showMenuScreen);

btnPause.addEventListener("click", () => {
  state.paused = !state.paused;
  btnPause.textContent = state.paused ? "▶ 继续" : "⏸ 暂停";
  if (!state.paused) clock.getDelta();
});

function setSpeed(mult) {
  state.speed = mult;
  btnSpeed1.classList.toggle("active", mult === 1);
  btnSpeed4.classList.toggle("active", mult === 4);
  btnSpeed8.classList.toggle("active", mult === 8);
}
btnSpeed1.addEventListener("click", () => setSpeed(1));
btnSpeed4.addEventListener("click", () => setSpeed(4));
btnSpeed8.addEventListener("click", () => setSpeed(8));

/* ---------- 启动 ---------- */
initThree();

// 菜单界面背景：静态渲染 3D 场景
(function idleLoop() {
  const dt = clock.getDelta();
  if (!state._loopStarted) {
    updateScene(0);
  }
  requestAnimationFrame(idleLoop);
})();

console.log("[Drone Sim] Frontend loaded, Three.js ready");
