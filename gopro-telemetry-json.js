#!/usr/bin/env node

const gpmfExtract = require("gpmf-extract");
const goproTelemetry = require("gopro-telemetry");
const fs = require("fs");
const path = require("path");

const inputPath = process.argv[2];

if (!inputPath) {
  console.error("Usage: node gopro-telemetry-json.js <video-file> <output-file>.telemetry.csv");
  process.exit(1);
}

if (!fs.existsSync(inputPath)) {
  console.error(`File not found: ${inputPath}`);
  process.exit(1);
}

const parsed = path.parse(inputPath);
const outputPath = process.argv[3] || path.join(`${parsed.name}.telemetry.csv`);

const file = fs.readFileSync(inputPath);

function cleanHeader(header) {
  const dashIndex = header.indexOf("-");
  if (dashIndex === -1) {
	return header.trim();
  }

  return header.slice(dashIndex + 1).trim();
}

function parseCsv(csvText) {
  const lines = csvText.trim().split(/\r?\n/);
  const rawHeaders = lines[0].split(",");
  
  const headers = rawHeaders.map(cleanHeader);

  return lines.slice(1).map((line) => {
	const values = line.split(",");
	const row = {};

	headers.forEach((header, i) => {
	  row[header] = values[i];
	});

	return row;
  });
}

function toCsv(rows) {
  if (rows.length === 0) return "";

  const headers = Array.from(
	rows.reduce((set, row) => {
	  Object.keys(row).forEach((key) => set.add(key));
	  return set;
	}, new Set())
  );

  const escape = (value) => {
	if (value === undefined || value === null) return "";
	const str = String(value);
	return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
  };

  return [
	headers.join(","),
	...rows.map((row) => headers.map((h) => escape(row[h])).join(",")),
  ].join("\n");
}

function mergeTelemetryCsvStreams(csvByStream, joinKey = "cts") {
  const merged = new Map();

  for (const [streamName, csvText] of Object.entries(csvByStream)) {
	const cleanStreamName = cleanHeader(streamName);
	const rows = parseCsv(csvText);

	for (const row of rows) {
	  const key = row[joinKey];

	  if (!key) continue;

	  if (!merged.has(key)) {
		merged.set(key, {
		  [joinKey]: key,
		  date: row.date,
		});
	  }

	  const outputRow = merged.get(key);

	  for (const [col, value] of Object.entries(row)) {
		if (col === joinKey || col === "date") continue;
		outputRow[`${cleanStreamName}_${col}`] = value;
	  }
	}
  }

  return Array.from(merged.values()).sort(
	(a, b) => Number(a[joinKey]) - Number(b[joinKey])
  );
}

gpmfExtract(file)
  .then((extracted) => {
	// goproTelemetry(extracted, {}, (telemetry) => {
	//   fs.writeFileSync(outputPath, JSON.stringify(telemetry, null, 2));
	//   console.log(`Telemetry saved: ${outputPath}`);
	// });
	goproTelemetry(extracted, {
	  preset: "csv",
	  // stream: ["ACCL", "GYRO", "GPS5"]
	}, (csv) => {
		const rows = mergeTelemetryCsvStreams(csv, "date");
		const combinedCsv = toCsv(rows);
		fs.writeFileSync(outputPath, combinedCsv);
	  console.log(`Telemetry saved: ${outputPath}`);
	});
  })
  .catch((error) => {
	console.error("Failed to extract telemetry:");
	console.error(error);
	process.exit(1);
  });
  