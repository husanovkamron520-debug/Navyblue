/* 3D yadro: canvas 2D, WebGL'siz. Sahna addBox() bilan to'ldiriladi. */
var cv = document.getElementById("scene"), ctx = cv.getContext("2d");
var W = 300, H = 300, DPR = window.devicePixelRatio || 1;
function resize() {
  W = cv.clientWidth || window.innerWidth; H = cv.clientHeight || window.innerHeight;
  cv.width = W * DPR; cv.height = H * DPR; ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
}
window.addEventListener("resize", resize); resize();
var cam = { yaw: 0.8, pitch: 0.55, dist: 22, focal: 700 };
var boxes = [];
function addBox(x, y, z, w, h, d, color) { boxes.push({ x: x, y: y, z: z, w: w, h: h, d: d, color: color || "#00e5ff" }); }
function clearBoxes() { boxes.length = 0; }
function shade(hex, k) {
  var n = parseInt(hex.slice(1), 16);
  var r = Math.min(255, ((n >> 16) & 255) * k) | 0, g = Math.min(255, ((n >> 8) & 255) * k) | 0, b = Math.min(255, (n & 255) * k) | 0;
  return "rgb(" + r + "," + g + "," + b + ")";
}
function project(px, py, pz) {
  var cy = Math.cos(cam.yaw), sy = Math.sin(cam.yaw), cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);
  var x = px * cy - pz * sy, z = px * sy + pz * cy;
  var y = py * cp - z * sp, zz = py * sp + z * cp;
  var depth = Math.max(0.5, cam.dist + zz), s = cam.focal / depth;
  return { x: W / 2 + x * s, y: H * 0.62 - y * s, d: depth };
}
function drawScene() {
  ctx.clearRect(0, 0, W, H);
  var faces = [];
  for (var i = 0; i < boxes.length; i++) {
    var b = boxes[i], x0 = b.x, x1 = b.x + b.w, y0 = b.y, y1 = b.y + b.h, z0 = b.z, z1 = b.z + b.d;
    var c = [[x0,y0,z0],[x1,y0,z0],[x1,y0,z1],[x0,y0,z1],[x0,y1,z0],[x1,y1,z0],[x1,y1,z1],[x0,y1,z1]].map(function (p) { return project(p[0], p[1], p[2]); });
    var defs = [[[4,5,6,7],1.15],[[0,1,5,4],0.9],[[1,2,6,5],0.7],[[2,3,7,6],0.8],[[3,0,4,7],0.6],[[0,3,2,1],0.5]];
    for (var j = 0; j < defs.length; j++) {
      var idx = defs[j][0], pts = idx.map(function (k) { return c[k]; });
      var dd = (pts[0].d + pts[1].d + pts[2].d + pts[3].d) / 4;
      faces.push({ pts: pts, d: dd, col: shade(b.color, defs[j][1]) });
    }
  }
  faces.sort(function (a, b) { return b.d - a.d; });
  for (var f = 0; f < faces.length; f++) {
    var F = faces[f]; ctx.beginPath(); ctx.moveTo(F.pts[0].x, F.pts[0].y);
    for (var q = 1; q < 4; q++) ctx.lineTo(F.pts[q].x, F.pts[q].y);
    ctx.closePath(); ctx.fillStyle = F.col; ctx.fill(); ctx.strokeStyle = "rgba(0,229,255,0.35)"; ctx.lineWidth = 1; ctx.stroke();
  }
}
var drag = null;
function pdown(x, y) { drag = { x: x, y: y }; }
function pmove(x, y) {
  if (!drag) return;
  cam.yaw += (x - drag.x) * 0.01; cam.pitch = Math.max(0.1, Math.min(1.45, cam.pitch + (y - drag.y) * 0.01));
  drag = { x: x, y: y };
}
cv.addEventListener("mousedown", function (e) { pdown(e.clientX, e.clientY); });
window.addEventListener("mousemove", function (e) { pmove(e.clientX, e.clientY); });
window.addEventListener("mouseup", function () { drag = null; });
cv.addEventListener("touchstart", function (e) { var t = e.touches[0]; pdown(t.clientX, t.clientY); e.preventDefault(); }, { passive: false });
cv.addEventListener("touchmove", function (e) { var t = e.touches[0]; pmove(t.clientX, t.clientY); e.preventDefault(); }, { passive: false });
cv.addEventListener("touchend", function () { drag = null; });
cv.addEventListener("wheel", function (e) { cam.dist = Math.max(8, Math.min(60, cam.dist + e.deltaY * 0.02)); e.preventDefault(); }, { passive: false });
function zoomBy(k) { cam.dist = Math.max(8, Math.min(60, cam.dist * k)); }
function loop() { drawScene(); requestAnimationFrame(loop); }
