// Click a tile to print its matched video path and tile number.

PImage im;
JSONArray matches;

int nbTX = 27, nbTY = 27;     // grid (for tile index only)
float tXS, tYS;               // tile size in source pixels (computed once)

float srcW = -1, srcH = -1;   // canvas size used in JSON "box" coords
int lastHit = -1;

void setup() {
  size(1440, 810);
  // la mosaique courante, reconstituee a partir des vraies images
  im = loadImage("../out_mosaic/matches_exhaustif_reel.jpg");
  if (im == null) im = loadImage("preview.png");     // repli : celle de 2025
  if (im == null) {
    println("[warn] aucun apercu trouve -> fond gris.");
  }
  matches = loadJSONArray("../out_mosaic/matches_exhaustif.json");
  if (matches == null) {
    // fallback: also try local data folder
    matches = loadJSONArray("../out_mosaic/matches_pass.json");
  }
  if (matches == null) {
    throw new RuntimeException("matches introuvable : lance chercher_tuiles.py");
  }

  // Detect the source canvas size from the max 'box' right/bottom
  float maxRight = 0, maxBottom = 0;
  for (int i = 0; i < matches.size(); i++) {
    JSONObject it = matches.getJSONObject(i);
    JSONArray box = it.getJSONArray("box"); // [x0,y0,x1,y1] in source pixels
    maxRight = max(maxRight, box.getFloat(2));
    maxBottom = max(maxBottom, box.getFloat(3));
  }
  srcW = maxRight;
  srcH = maxBottom;

  // Derive tile sizes from source grid if the image matches that grid
  tXS = srcW / nbTX;
  tYS = srcH / nbTY;

  println("[info] Loaded " + matches.size() + " tiles; srcW=" + srcW + " srcH=" + srcH);
}

void draw() {
  background(24);
  if (im != null) {
    image(im, 0, 0, width, height);
  }

  // optional: draw a subtle highlight around the last clicked tile
  if (lastHit >= 0 && lastHit < matches.size()) {
    JSONObject it = matches.getJSONObject(lastHit);
    JSONArray b = it.getJSONArray("box");
    // scale box from source → screen
    float sx = width / srcW;
    float sy = height / srcH;
    float x0 = b.getFloat(0) * sx;
    float y0 = b.getFloat(1) * sy;
    float x1 = b.getFloat(2) * sx;
    float y1 = b.getFloat(3) * sy;

    noFill();
    stroke(255);
    strokeWeight(2);
    rect(x0, y0, x1 - x0, y1 - y0);
  }
}

void mousePressed() {
  // Find which JSON "box" contains the click (in screen coords → source coords)
  float sx = srcW / width;
  float sy = srcH / height;
  float mxSrc = mouseX * sx;
  float mySrc = mouseY * sy;

  int hit = -1;
  for (int i = 0; i < matches.size(); i++) {
    JSONObject it = matches.getJSONObject(i);
    JSONArray b = it.getJSONArray("box"); // [x0,y0,x1,y1]
    float x0 = b.getFloat(0), y0 = b.getFloat(1);
    float x1 = b.getFloat(2), y1 = b.getFloat(3);
    if (mxSrc >= x0 && mxSrc < x1 && mySrc >= y0 && mySrc < y1) {
      hit = i;
      break;
    }
  }

  if (hit == -1) {
    println("No tile under click.");
    lastHit = -1;
    return;
  }

  lastHit = hit;

  // Compute the grid index (like your original tNb) from normalized coords
  float xNorm = (mouseX / (float)width);
  float yNorm = (mouseY / (float)height);
  int tNb = floor(floor(xNorm * nbTX) + floor(yNorm * nbTY) * nbTX);

  JSONObject it = matches.getJSONObject(hit);
  JSONObject m = it.getJSONObject("match");
  String vid = m.getString("video");
  println("tile number " + tNb + " | json index " + hit + " | video: " + vid);
}
