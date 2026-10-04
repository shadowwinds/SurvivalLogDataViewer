(() => {
  "use strict";

  function conditions(environment, choice, planter, manual = null) {
    const powered = planter?.needs_power && choice.power === "on";
    const lightBonus = (planter?.light_bonus || 0) + (powered ? planter.electric_light || 0 : 0);
    const heatBonus = (planter?.heat_bonus || 0) + (powered ? planter.electric_heat || 0 : 0);
    let light, cold, scenario, location, parameters, roomHeat, deviceHeat = 0;
    if (manual) {
      ({light, cold} = manual);
    } else {
      scenario = environment?.scenarios.find(row => row.weather === choice.weather && row.cold_wave === Number(choice.cold_wave));
      location = environment?.locations.find(row => row.key === choice.location);
      parameters = location?.parameters.find(row => row.weather_id === scenario?.id) ||
        location?.parameters.find(row => row.weather_id === 0);
      if (!scenario || !location || !parameters) return {valid: false, planter};
      if (location.device_heat) deviceHeat = environment.heaters.reduce((sum, heater) =>
        sum + (choice[heater.key] ? heater.heat : 0), 0);
      roomHeat = parameters.heat + deviceHeat;
      if (environment.heat_cap > 0) roomHeat = Math.min(roomHeat, environment.heat_cap);
      light = scenario.light * parameters.light_multiplier;
      cold = scenario.cold - roomHeat;
    }
    const valid = (light === null || (Number.isFinite(light) && light >= 0)) &&
      (cold === null || Number.isFinite(cold));
    return {valid, planter, scenario, location, parameters, deviceHeat, roomHeat, lightBonus, heatBonus,
      light: light === null ? null : light + lightBonus,
      cold: cold === null ? null : Math.max(0, cold - heatBonus)};
  }

  function problems(entry, current) {
    if (!current.valid) return ["请输入有效的环境数值"];
    const plant = entry.plant, reasons = [];
    if (current.planter && (!Number.isFinite(plant?.size) || plant.size <= 0 ||
        !Number.isFinite(current.planter.capacity) || plant.size > current.planter.capacity)) reasons.push("容器空间不足");
    if (current.light !== null && (!Number.isFinite(plant?.light_need) || current.light < plant.light_need)) reasons.push("光照不足");
    if (current.cold !== null && (!Number.isFinite(plant?.cold_resistance) || current.cold > plant.cold_resistance)) reasons.push("寒冷过高");
    return reasons;
  }

  function compare(a, b, sort, current) {
    const suitability = Number(problems(a, current).length > 0) - Number(problems(b, current).length > 0);
    if (suitability) return suitability;
    const numeric = (entry, field, descending = false) => Number.isFinite(entry.plant?.[field]) ?
      entry.plant[field] * (descending ? -1 : 1) : Infinity;
    const difference = field => numeric(a, field) - numeric(b, field);
    let rank = 0;
    if (sort === "plant-food") rank = Number(Boolean(b.plant?.food_harvest)) - Number(Boolean(a.plant?.food_harvest));
    if (sort === "plant-space") rank = difference("size");
    if (sort === "plant-cold") rank = numeric(a, "cold_resistance", true) - numeric(b, "cold_resistance", true);
    if (sort === "plant-light") rank = difference("light_need");
    return (Number.isNaN(rank) ? 0 : rank) || difference("growth_seconds") || difference("size") || a.id - b.id;
  }

  window.Planting = {conditions, problems, compare};
})();
