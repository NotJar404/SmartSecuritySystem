using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace WebApp.Models
{
    [Table("alarm_settings")]
    public class AlarmSetting
    {
        [Key]
        [Column("setting_id")]
        public int SettingId { get; set; }

        [Column("name")]
        public string Name { get; set; } = string.Empty;

        [Column("type")]
        public string Type { get; set; } = string.Empty;

        [Column("is_enabled")]
        public bool IsEnabled { get; set; } = true;

        // Helper for the UI icons
        [NotMapped]
        public string IconClass => Type.ToLower() switch
        {
            "intrusion" => "fas fa-shield-alt",
            "fire" => "fas fa-fire-extinguisher",
            "earthquake" => "fas fa-house-damage",
            "forcedentry" => "fas fa-ambulance",
            _ => "fas fa-bell"
        };
    }
}