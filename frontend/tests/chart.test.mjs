import assert from "node:assert/strict";
import test from "node:test";
import * as echarts from "echarts/core";
import * as charts from "echarts/charts";
import * as components from "echarts/components";
import * as renderers from "echarts/renderers";
import { loadModule, mount } from "./helpers.mjs";

test("the dashboard risk series renders actual bars", (t) => {
  const component = mount(() =>
    loadModule(
      "src/components/AnalyticsChart.vue",
      { defineProps: () => ({ option: {} }) },
      {
        "echarts/core": echarts,
        "echarts/charts": charts,
        "echarts/components": components,
        "echarts/renderers": renderers,
      },
    ),
  );
  t.after(component.unmount);
  echarts.use(renderers.SVGRenderer);
  const chart = echarts.init(null, null, {
    renderer: "svg",
    ssr: true,
    width: 320,
    height: 200,
  });
  t.after(() => chart.dispose());
  chart.setOption({
    xAxis: { type: "category", data: ["day"] },
    yAxis: {},
    series: [{ type: "bar", data: [3], itemStyle: { color: "#ed1234" } }],
  });
  assert.match(
    chart.renderToSVGString(),
    /#ed1234/,
    "the risk bar must be present in rendered output",
  );
});
