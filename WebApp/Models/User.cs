using System;
using System.ComponentModel.DataAnnotations;

namespace SmartSecuritySystem.Models
{
    public class User
    {
        public int Id { get; set; }

        [Required]
        public string Username { get; set; }

        [Required]
        public string PasswordHash { get; set; }

        [Required]
        public string Role { get; set; } // "Admin" or "Security"

        // 🔽 NEW FIELDS FOR ADMIN DASHBOARD

        [Required]
        public string Name { get; set; }

        [Required]
        [EmailAddress]
        public string Email { get; set; }

        public string Status { get; set; } = "Active"; // Active / Inactive

        public DateTime? LastLogin { get; set; }
    }
}