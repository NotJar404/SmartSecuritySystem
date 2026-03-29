using System;
using System.ComponentModel.DataAnnotations;

namespace WebApp.Models
{
    public class Camera
    {
        public int Id { get; set; }

        // ===============================
        // BASIC INFO
        // ===============================
        [Required]
        [StringLength(100)]
        public string Name { get; set; }

        [Required]
        [StringLength(150)]
        public string Location { get; set; }

        // ===============================
        // NETWORK
        // ===============================
        [Display(Name = "IP Address")]
        [RegularExpression(@"^(\d{1,3}\.){3}\d{1,3}$", ErrorMessage = "Invalid IP format")]
        public string IpAddress { get; set; }

        [Range(1, 65535)]
        public int Port { get; set; } = 554;

        // ===============================
        // VIDEO SETTINGS
        // ===============================
        public string Resolution { get; set; } = "1920x1080";

        [Display(Name = "FPS")]
        [Range(1, 120)]
        public int Fps { get; set; } = 30;

        // ===============================
        // FEATURES
        // ===============================
        public bool Recording { get; set; } = true;

        public bool Motion { get; set; } = true;

        // ===============================
        // SYSTEM
        // ===============================
        public bool IsOnline { get; set; } = true;

        public DateTime CreatedAt { get; set; } = DateTime.Now;
    }
}