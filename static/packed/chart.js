NDIGITS = 2;
function round(number, precision) {
  var pow = Math.pow(10, precision);
  return Math.round(number * pow) / pow;
}

nv.addGraph(function() {  
  var chart, data;

  if (LAYOUT === 'line') {

    chart = nv.models.lineChart()
      .forceY([0, 100]);
    chart.yAxis.tickFormat(d3.format(',.0f'));
    chart.tooltipContent(function(col, x, y) { 
      return '(' + x + ', ' + y + ')';
    });

    data = $.map(DATA, function(series, i) {
      var values = $.map(series, function(points, ii) {
        return {x: ii, y: parseFloat(points)};
      });
      return {
        values: values,
        key: LABELS[i]
      };
    });

  } else if (LAYOUT === 'pie') {

    chart = nv.models.pieChart()
      .x(function(d) { return d.label; })
      .y(function(d) { return d.value; })
      .showLabels(true);
    chart.tooltipContent = null;

    data = [{
      values: $.map(DATA, function(points, i) {
        return {label: LABELS[i], value: parseFloat(points)};
      })
    }];

  } else if (LAYOUT === 'bar') {

    chart = nv.models.multiBarChart()
      .tooltips(false);

    data = $.map(DATA, function(o,i) {
      return {
        key: o[0],
        values: $.map(o[1], function(oo,ii) {
          var label = (LABELS[ii] === undefined) ? 'Column ' + (ii+1) : LABELS[ii];
          return {x: label, y: parseFloat(oo)};
        })
      };
    });

  } else if (LAYOUT === 'hist') {

    var min = Math.min.apply(this, DATA);
    var max = Math.max.apply(this, DATA);

    // sort data into bins
    var nbins = 1 + Math.pow(DATA.length, 1/3);
    var hist = d3.layout.histogram()
      .bins(nbins)
      .frequency(true);
    var accum = hist(DATA);

    chart = nv.models.discreteBarChart()
      .x(function(d) { return d.bin; })
      .y(function(d) { return d.freq; })
      .tooltips(false)
      .showValues(true);
    C=chart;
    chart.yAxis.tickFormat(d3.format(',.0f'));
    chart.valueFormat(d3.format(',.0f'));

    data = [{
      values: $.map(accum, function(o,i) {
        return { 
          bin: round(o.x, NDIGITS) + ' to ' + round(o.x+o.dx, NDIGITS),
          freq: round(o.y, NDIGITS)
        };
      })
    }];

  } else if (LAYOUT === 'scatter') {

  }
  
  d3.select('#chart svg')
    .datum(function() { return data; })
    .transition().duration(250)
    .call(chart);
  
  nv.utils.windowResize(chart.update);
  
  return chart;
});
